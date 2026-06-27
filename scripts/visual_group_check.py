#!/usr/bin/env python3
"""滚到底 + 抓屏 + 读 UI 文字，对照群里可见内容。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

HOST, R, PW = "46.183.27.174", "/home/bot/55chat-bot", "Aa112211@@785*"
OUT = Path(__file__).resolve().parents[1] / "logs" / "visual-now"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)
    sf = s.open_sftp()

    def run(cmd: str, t: int = 60) -> str:
        _, o, e = s.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")

    for port, label in (("60478", "listener"), ("52718", "clicker")):
        serial = f"127.0.0.1:{port}"
        for _ in range(4):
            # 手指上滑 → 滚到最新消息（底部）
            run(f"adb -s {serial} shell input swipe 360 1100 360 350 220")
            time.sleep(0.35)
        run(f"adb -s {serial} exec-out screencap -p > /tmp/{label}_bottom.png")
        ui = run(
            f"""python3 - <<'PY'
import sys
sys.path.insert(0, "{R}")
import bot_55chat_daemon as d
serial = "{serial}"
root = d.ui_hierarchy(serial)
texts = [t for t in d.collect_ui_texts(root) if t.strip()]
periods = [t for t in texts if "期" in t or "3449" in t or "新一" in t or "开奖" in t]
has_913x = [t for t in texts if any(x in t for x in ("344913", "344912", "344911"))]
print("ACTIVITY", d.is_group_chat_activity(serial))
print("HAS_912_913", " | ".join(has_913x[-6:]))
print("PERIODS", " | ".join(periods[-8:]))
print("TAIL", " | ".join(texts[-12:]))
PY"""
        )
        sf.get(f"/tmp/{label}_bottom.png", str(OUT / f"{label}_bottom.png"))
        print(f"\n===== {label} ({serial}) =====")
        print(ui.strip())

    sf.close()
    s.close()


if __name__ == "__main__":
    main()
