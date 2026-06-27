#!/usr/bin/env python3
"""左机发图：群里可见 ImageView + 连续 2 期批量发图成功才停。"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
SERIAL = "127.0.0.1:52718"
ROOT = Path(__file__).resolve().parents[1]
NEED = 2
POLL = 25
MAX_MIN = 90


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
    sf.put(str(ROOT / "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
    sf.put(str(ROOT / "config" / "pinned-coords.json"), f"{R}/config/pinned-coords.json")
    sf.close()


def scroll_bottom(ssh: paramiko.SSHClient) -> None:
    for _ in range(4):
        run(ssh, f"adb -s {SERIAL} shell input swipe 360 1100 360 350 220")
        time.sleep(0.25)


def chat_images(ssh: paramiko.SSHClient) -> int:
    scroll_bottom(ssh)
    out = run(
        ssh,
        f"""python3 - <<'PY'
import sys
sys.path.insert(0, "{R}")
import bot_55chat_daemon as d
serial="{SERIAL}"
bot={{"id":"bot-3","associatedGroup":"苍井空测试"}}
root=d.ui_hierarchy(serial)
ib=None
if root:
    for node in root.iter("node"):
        if "EditText" in (node.attrib.get("class") or ""):
            b=d.parse_bounds(node.attrib.get("bounds",""))
            if b: ib=b; break
n=0
if root and ib:
    y_max=ib[1]-16
    for node in root.iter("node"):
        if "ImageView" not in (node.attrib.get("class") or ""): continue
        b=d.parse_bounds(node.attrib.get("bounds",""))
        if not b or b[3]>y_max or b[1]<80: continue
        bw,bh=b[2]-b[0],b[3]-b[1]
        if bw>=100 and bh>=100: n+=1
print(n)
PY""",
        60,
    )
    try:
        return int(out.strip().splitlines()[-1])
    except ValueError:
        return 0


def img_rounds_from_log(ssh: paramiko.SSHClient) -> list[int]:
    raw = run(ssh, f"tail -n 6000 {R}/logs/bot.log")
    rids: list[int] = []
    pending: int | None = None
    for ln in raw.splitlines():
        m = re.search(r"结算 rid=(\d+)", ln)
        if m:
            pending = int(m.group(1))
        if "批量发图成功" in ln and pending is not None:
            rids.append(pending)
            pending = None
    return rids


def streak(rids: list[int]) -> int:
    if not rids:
        return 0
    u = sorted(set(rids))
    best = cur = 1
    for i in range(1, len(u)):
        if u[i] == u[i - 1] + 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def main() -> int:
    ssh = connect()
    upload(ssh)
    deadline = time.time() + MAX_MIN * 60
    print(f"[watch-img] 目标连续 {NEED} 期发图成功 + 群里可见图片", flush=True)

    while time.time() < deadline:
        imgs = chat_images(ssh)
        rids = img_rounds_from_log(ssh)
        st = streak(rids)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] chat_images={imgs} img_rounds={rids[-5:]} streak={st}", flush=True)

        if st >= NEED and imgs >= 1:
            out = {
                "ok": True,
                "streak": st,
                "rounds": rids[-NEED:],
                "chat_images": imgs,
                "utc": datetime.now(timezone.utc).isoformat(),
            }
            (ROOT / "logs" / "clicker_img_2rounds.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print("DONE", json.dumps(out, ensure_ascii=False))
            ssh.close()
            return 0
        time.sleep(POLL)

    ssh.close()
    print(json.dumps({"ok": False, "streak": streak(img_rounds_from_log(ssh))}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
