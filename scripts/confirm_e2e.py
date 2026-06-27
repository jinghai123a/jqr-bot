#!/usr/bin/env python3
"""
端到端确认：不靠 grep 猜，用 Activity + 视觉三连拍 + 可选发一条探针。
100% PASS 才报正常。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import paramiko

HOST, R = "46.183.27.174", "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]


def ssh():
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password="Aa112211@@785*", timeout=30)
    return s


def run(ssh, cmd: str, t: int = 90) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def activity_group(serial: str, ssh) -> bool:
    out = run(
        ssh,
        f"python3 - <<'PY'\nimport sys\nsys.path.insert(0,'{R}')\nimport bot_55chat_daemon as d\nprint('OK' if d.is_group_chat_activity('{serial}') else 'NO')\nPY",
    )
    return "OK" in out


def visual_once(ssh) -> dict:
    out = run(
        ssh,
        f"python3 {R}/scripts/vmos_visual_monitor.py --both --once 2>&1",
    )
    states = {}
    for line in out.splitlines():
        m = re.search(r"(clicker|listener)\s+(\S+)\s+state=(\w+)", line)
        if m:
            states[m.group(1)] = m.group(3)
    return states


def main() -> int:
    s = ssh()
    fails: list[str] = []

    print("=== 1/4 Activity（GroupChatActivity）===")
    for label, port in (("clicker", "52718"), ("listener", "60478")):
        serial = f"127.0.0.1:{port}"
        ok = activity_group(serial, s)
        print(f"  {label}: {'GroupChatActivity OK' if ok else 'NOT in group chat activity'}")
        if not ok and label == "listener":
            fails.append(f"右机 Activity 不在群聊")

    print("\n=== 2/4 视觉三连拍（5s 间隔）===")
    listener_hits = 0
    for i in range(3):
        st = visual_once(s)
        act_ok = activity_group("127.0.0.1:60478", s)
        print(f"  shot{i+1}: clicker={st.get('clicker','?')} listener={st.get('listener','?')} activity={act_ok}")
        if st.get("listener") == "target_group" and act_ok:
            listener_hits += 1
        if st.get("clicker") != "target_group":
            fails.append(f"左机视觉 shot{i+1}={st.get('clicker')}")
        if not act_ok:
            fails.append(f"右机 Activity shot{i+1}=NO")
        time.sleep(5)
    if listener_hits < 2:
        fails.append(f"右机视觉+Activity 仅 {listener_hits}/3 次达标")

    print("\n=== 3/4 探针发送（右机 pipe 灌字+发送，不污染群）===")
    probe = run(
        s,
        f"""python3 - <<'PY'
import os, sys
sys.path.insert(0, "{R}")
os.chdir("{R}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="127.0.0.1:60478"
bot={{"id":"bot-4","associatedGroup":"苍井空测试"}}
if not d.listener_in_group_for_send(d.ui_hierarchy(serial), bot, serial):
    print("SKIP:not_in_group"); raise SystemExit(2)
sx, sy = d.listener_pinned_send_xy(None, None)
ok = d.send_chat_reply(serial, bot, "[probe]", None, (sx, sy), None, group_ok=True)
print("PROBE_SENT" if ok else "PROBE_FAIL")
PY""",
        60,
    )
    print(probe.strip())
    if "PROBE_SENT" not in probe:
        fails.append("右机探针发送失败")
    elif "SKIP:not_in_group" in probe:
        fails.append("探针判定不在群")

    print("\n=== 4/4 verify 脚本 ===")
    s.close()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_dual_brain.py")], cwd=ROOT)
    if r.returncode != 0:
        fails.append("verify_dual_brain 未全过")

    print("\n========== 结论 ==========")
    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        print("=> 不能确认 100% 正常")
        return 1
    print("=> 100% 确认：双机在群、视觉稳定、探针发送成功、verify 全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
