#!/usr/bin/env python3
"""VPS 即时诊断：双机 UI + 期号 + 最近日志。"""
from __future__ import annotations

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"


def main() -> None:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)

    def run(cmd: str, t: int = 120) -> str:
        _, o, e = s.exec_command(cmd, timeout=t)
        return (o.read() + e.read()).decode("utf-8", "replace")

    print("=== ADB ===")
    print(run("adb devices -l").strip())
    print("\n=== DAEMON ===")
    print(run("pgrep -af bot_55chat_daemon || echo DEAD").strip())

    ui_py = """
import sys
sys.path.insert(0, "%s")
import bot_55chat_daemon as d
for port, label in [("60478", "listener"), ("52718", "clicker")]:
    serial = "127.0.0.1:" + port
    for _ in range(4):
        d.adb_run(serial, "shell", "input", "swipe", "360", "1100", "360", "350", "220")
        d.w(0.25, 0.05)
    root = d.ui_hierarchy(serial)
    bot = {"id": "bot-4" if label == "listener" else "bot-3", "associatedGroup": "苍井空测试"}
    texts = d.collect_ui_texts(root) if root else []
    periods = [t for t in texts if any(k in t for k in ("期", "新一", "开奖", "封盘"))]
    ctx = d.describe_screen_context(root, bot, serial) if root else None
    n_img = 0
    if root:
        ib = None
        for node in root.iter("node"):
            if "EditText" in (node.attrib.get("class") or ""):
                b = d.parse_bounds(node.attrib.get("bounds", ""))
                if b:
                    ib = b
                    break
        if ib:
            ym = ib[1] - 12
            for node in root.iter("node"):
                cls = node.attrib.get("class") or ""
                if not any(k in cls for k in ("Image", "Texture", "Video")):
                    continue
                b = d.parse_bounds(node.attrib.get("bounds", ""))
                if not b or b[3] > ym or b[1] < 60:
                    continue
                bw, bh = b[2] - b[0], b[3] - b[1]
                if bw >= 70 and bh >= 70:
                    n_img += 1
    print("=== " + label + " ===")
    print("ACTIVITY", d.is_group_chat_activity(serial))
    print("PAGE", ctx.page if ctx else "?")
    print("NODES", len(list(root.iter("node"))) if root else 0)
    print("CHAT_IMAGES", n_img)
    print("PERIODS", " | ".join(periods[-6:]))
    print("TAIL", " | ".join(texts[-8:]))
""" % (R,)

    print("\n=== UI STATE ===")
    print(run(f"python3 - <<'PY'\n{ui_py}\nPY", 180).strip())

    meta_py = f"""
import sys, os
sys.path.insert(0, "{R}")
os.chdir("{R}")
import bot_55chat_daemon as d
settings = d.merge_settings(d.api("GET", "/api/settings"))
rid, iv, rem = d.active_round_timing(settings)
print("CUR_RID", rid, "REM", int(rem))
"""
    print("\n=== ROUND ===")
    print(run(f"python3 - <<'PY'\n{meta_py}\nPY").strip())

    print("\n=== RECENT LOG (settle/img/open/pipe) ===")
    print(
        run(
            f"grep -E '结算 rid=|批量发图|开局公告|pipe\\+b64' {R}/logs/bot.log | tail -n 30"
        ).strip()
    )
    s.close()


if __name__ == "__main__":
    main()
