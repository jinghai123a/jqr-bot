#!/usr/bin/env python3
"""左机发图：log + 抓屏 + UI ImageView，成功才停。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
SERIAL = "127.0.0.1:52718"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs" / "visual-now"
POLL_SEC = 25
MAX_MIN = 45


def connect() -> paramiko.SSHClient:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)
    return s


def run(ssh: paramiko.SSHClient, cmd: str, t: int = 120) -> str:
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return (o.read() + e.read()).decode("utf-8", "replace")


def upload(ssh: paramiko.SSHClient) -> None:
    sf = ssh.open_sftp()
    for rel in ("bot_55chat_daemon.py", "config/pinned-coords.json"):
        p = ROOT / rel
        if p.is_file():
            sf.put(str(p), f"{R}/{rel}")
    sf.close()


def scroll_chat_bottom(ssh: paramiko.SSHClient) -> None:
    for _ in range(4):
        run(ssh, f"adb -s {SERIAL} shell input swipe 360 1100 360 350 220")
        time.sleep(0.3)


def visual_image_count(ssh: paramiko.SSHClient) -> dict:
    scroll_chat_bottom(ssh)
    out = run(
        ssh,
        f"""python3 - <<'PY'
import sys
sys.path.insert(0, "{R}")
import bot_55chat_daemon as d
serial = "{SERIAL}"
bot = {{"id": "bot-3", "associatedGroup": "苍井空测试"}}
root = d.ui_hierarchy(serial)
in_group = d.in_target_group_chat(root, bot, serial)
act = d.is_group_chat_activity(serial)
sh = d.screen_height(root) if root else 0
sw = 720
imgs = []
if root is not None:
    ib = None
    for node in root.iter("node"):
        if "EditText" in (node.attrib.get("class") or ""):
            b = d.parse_bounds(node.attrib.get("bounds", ""))
            if b:
                ib = b
                break
    y_max = (ib[1] - 20) if ib else int(sh * 0.82)
    for node in root.iter("node"):
        cls = node.attrib.get("class") or ""
        if "ImageView" not in cls and "Image" not in cls:
            continue
        b = d.parse_bounds(node.attrib.get("bounds", ""))
        if not b or b[3] > y_max or b[1] < 80:
            continue
        bw, bh = b[2] - b[0], b[3] - b[1]
        if bw >= 100 and bh >= 100 and b[0] < 520:
            imgs.append((bw, bh, b[0], b[1]))
texts = d.collect_ui_texts(root) if root else []
periods = [t for t in texts if "期" in t and "3449" in t]
print("IN_GROUP", in_group, "ACTIVITY", act, "SCREEN", sw, sh)
print("CHAT_IMAGES", len(imgs), imgs[-5:])
print("PERIODS", " | ".join(periods[-4:]))
PY""",
        90,
    )
    info: dict = {"raw": out}
    for line in out.splitlines():
        if line.startswith("IN_GROUP"):
            parts = line.split()
            info["in_group"] = parts[1] == "True"
            info["activity"] = parts[3] == "True"
            if len(parts) >= 6:
                info["screen"] = f"{parts[5]}x{parts[6]}" if len(parts) > 6 else parts[5]
        elif line.startswith("CHAT_IMAGES"):
            m = re.search(r"CHAT_IMAGES (\d+)", line)
            if m:
                info["image_bubbles"] = int(m.group(1))
        elif line.startswith("PERIODS"):
            info["periods"] = line.replace("PERIODS ", "")
    run(ssh, f"adb -s {SERIAL} exec-out screencap -p > /tmp/clicker_watch.png")
    OUT.mkdir(parents=True, exist_ok=True)
    ssh.open_sftp().get("/tmp/clicker_watch.png", str(OUT / "clicker_watch.png"))
    return info


def recent_img_log(ssh: paramiko.SSHClient) -> tuple[bool, str]:
    raw = run(ssh, f"tail -n 5000 {R}/logs/bot.log")
    ok_lines = [ln for ln in raw.splitlines() if "批量发图成功" in ln or "左机 UI 发图成功" in ln]
    fail_lines = [
        ln
        for ln in raw.splitlines()
        if any(x in ln for x in ("批量发图失败", "批量发图未确认", "左机 UI 发图失败", "UI 发图失败"))
    ]
    last_ok = ok_lines[-1] if ok_lines else ""
    last_fail = fail_lines[-1] if fail_lines else ""
    ok_ts = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_ok)
    fail_ts = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_fail)
    log_ok = False
    if ok_ts:
        from datetime import datetime, timezone
        ts = datetime.strptime(ok_ts.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        log_ok = age < 600
        if fail_ts and fail_ts.group(1) > ok_ts.group(1):
            log_ok = False
    return log_ok, (last_ok or last_fail)[-140:]


def ensure_clicker_in_group(ssh: paramiko.SSHClient) -> None:
    run(
        ssh,
        f"""python3 - <<'PY'
import os, sys
sys.path.insert(0, "{R}")
os.chdir("{R}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="{SERIAL}"
bot={{"id":"bot-3","associatedGroup":"苍井空测试"}}
if not d.in_target_group_chat(d.ui_hierarchy(serial), bot, serial):
    d.ensure_clicker_in_group(serial, bot, reason="img-watch")
PY""",
        90,
    )


def probe_send_test_image(ssh: paramiko.SSHClient) -> str:
    """用现有结算截图路径试发一张（若有）。"""
    return run(
        ssh,
        f"""python3 - <<'PY'
import glob, os, sys
sys.path.insert(0, "{R}")
os.chdir("{R}")
for line in open("config/bot-start.env"):
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.strip().split("=",1); os.environ.setdefault(k,v)
import bot_55chat_daemon as d
serial="{SERIAL}"
bot={{"id":"bot-3","associatedGroup":"苍井空测试"}}
paths = sorted(glob.glob("data/captures/*.png"), key=os.path.getmtime)
if not paths:
    print("NO_CAPTURE"); raise SystemExit(2)
p = paths[-1]
if not d.in_target_group_chat(d.ui_hierarchy(serial), bot, serial):
    d.ensure_clicker_in_group(serial, bot, reason="probe-img")
snap = d.ui_snapshot(serial, chat=True)
ix = snap.input_xy
sy = snap.inbar_send or snap.keyboard_send
ok = d.send_chat_image(serial, bot, p, ix, sy, {{}}, group_ok=True)
print("PROBE_IMG_OK" if ok else "PROBE_IMG_FAIL", p)
PY""",
        180,
    )


def success(vis: dict, log_ok: bool) -> bool:
    bubbles = vis.get("image_bubbles", 0)
    return bool(vis.get("in_group")) and bubbles >= 1 and log_ok


def main() -> int:
    ssh = connect()
    upload(ssh)
    deadline = time.time() + MAX_MIN * 60
    last_probe = 0.0
    probe_count = 0

    while time.time() < deadline:
        ensure_clicker_in_group(ssh)
        vis = visual_image_count(ssh)
        log_ok, log_line = recent_img_log(ssh)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(
            f"[{ts}] bubbles={vis.get('image_bubbles',0)} in_group={vis.get('in_group')} "
            f"log_ok={log_ok} periods={vis.get('periods','')[:60]}",
            flush=True,
        )
        if success(vis, log_ok):
            result = {
                "ok": True,
                "image_bubbles": vis.get("image_bubbles"),
                "log": log_line,
                "utc": datetime.now(timezone.utc).isoformat(),
            }
            (ROOT / "logs" / "clicker_img_ok.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("DONE", json.dumps(result, ensure_ascii=False))
            ssh.close()
            return 0

        # 无图且久未成功 → 探针发一张
        if vis.get("image_bubbles", 0) < 1 and time.time() - last_probe > 120 and probe_count < 3:
            print(probe_send_test_image(ssh).strip(), flush=True)
            last_probe = time.time()
            probe_count += 1
            time.sleep(12)
            continue

        time.sleep(POLL_SEC)

    ssh.close()
    print(json.dumps({"ok": False, "reason": "timeout"}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
