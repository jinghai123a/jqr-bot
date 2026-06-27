#!/usr/bin/env python3
"""左机探针：批量发 3 张结算图并抓屏验证。"""
from __future__ import annotations

import glob
import os
import sys
import time
from pathlib import Path

import paramiko

HOST, R, PW = "46.183.27.174", "/home/bot/55chat-bot", "Aa112211@@785*"
SERIAL = "127.0.0.1:52718"
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)
    sf = s.open_sftp()
    sf.put(str(ROOT / "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
    sf.put(str(ROOT / "config" / "pinned-coords.json"), f"{R}/config/pinned-coords.json")
    sf.close()

    def run(cmd: str, t: int = 180) -> str:
        _, o, e = s.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")

    out = run(
        f"""python3 - <<'PY'
import glob, os, sys, re
sys.path.insert(0, "{R}")
os.chdir("{R}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="{SERIAL}"
bot={{"id":"bot-3","associatedGroup":"苍井空测试"}}
rid = max(int(re.search(r"(\\d+)", os.path.basename(p)).group(1)) for p in glob.glob("data/captures/pc28_*.png")[-5:])
paths = sorted([p for p in glob.glob(f"data/captures/*_{{rid}}_*.png") if os.path.isfile(p)])
if len(paths) < 3:
    paths = sorted(glob.glob("data/captures/*.png"), key=os.path.getmtime)[-3:]
print("PATHS", paths)
if not d.in_target_group_chat(d.ui_hierarchy(serial), bot, serial):
    d.ensure_clicker_in_group(serial, bot, reason="probe-batch")
snap = d.ui_snapshot(serial, chat=True)
ix, sy = snap.input_xy, snap.inbar_send or snap.keyboard_send
ok = d.send_chat_images_batch(serial, bot, paths, ix, sy, {{}}, group_ok=True)
print("BATCH_OK" if ok else "BATCH_FAIL")
root = d.ui_hierarchy(serial)
ib = snap.input_bounds
imgs = 0
if root is not None and ib:
    y_max = ib[1] - 16
    for node in root.iter("node"):
        if "ImageView" not in (node.attrib.get("class") or ""): continue
        b = d.parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[3] > y_max or b[1] < 80: continue
        bw, bh = b[2]-b[0], b[3]-b[1]
        if bw >= 100 and bh >= 100: imgs += 1
print("UI_IMAGES", imgs)
PY"""
    )
    print(out.strip())
    run(f"adb -s {SERIAL} exec-out screencap -p > /tmp/clicker_after_batch.png")
    out_dir = ROOT / "logs" / "visual-now"
    out_dir.mkdir(parents=True, exist_ok=True)
    s.open_sftp().get("/tmp/clicker_after_batch.png", str(out_dir / "clicker_after_batch.png"))
    s.close()
    return 0 if "BATCH_OK" in out and "UI_IMAGES" in out and int(out.split("UI_IMAGES")[-1].strip().split()[0]) >= 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
