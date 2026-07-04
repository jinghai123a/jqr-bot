#!/usr/bin/env python3
"""修复左机发图坐标 + 重载双进程。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"


def main() -> int:
    subprocess = __import__("subprocess")
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "sync_edge_android_coords.py")])

    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        for rel in (
            "bot_55chat_daemon.py",
            "config/pinned-coords.json",
            "edge_android/settle-left/edge_config.json",
        ):
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")

        print("=== bot-start env: 关 clicker-stay ===")
        print(
            ssh.run(
                f"grep -q BOT_CLICKER_STAY_IN_CHAT= {R}/config/bot-start.env && "
                f"sed -i 's/^BOT_CLICKER_STAY_IN_CHAT=.*/BOT_CLICKER_STAY_IN_CHAT=0/' {R}/config/bot-start.env || "
                f"echo BOT_CLICKER_STAY_IN_CHAT=0 >> {R}/config/bot-start.env",
                15,
            )
        )

        print("=== stop edge_adb_agent (避免与 spawn 抢左机) ===")
        print(ssh.run("pkill -f edge_adb_agent.py 2>/dev/null || true", 10))

        print(
            ssh.run(
                f"grep -q BOT_IMG_UPLOAD_WAIT_SEC= {R}/config/bot-start.env && "
                f"sed -i 's/^BOT_IMG_UPLOAD_WAIT_SEC=.*/BOT_IMG_UPLOAD_WAIT_SEC=18/' {R}/config/bot-start.env || "
                f"echo BOT_IMG_UPLOAD_WAIT_SEC=18 >> {R}/config/bot-start.env",
                15,
            )
        )

        print("=== reload dual workers ===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -15", 180))

        print("=== heal left to group ===")
        print(ssh.run(f"cd {R} && {R}/.venv/bin/python3 scripts/vps_heal_group_closure.py 2>&1 | tail -12", 120))

        left = "adb -P 5039 -s 127.0.0.1:52840"
        print(ssh.run(f"{left} shell rm -f /sdcard/DCIM/Camera/bot_*.png 2>/dev/null; echo dcim_cleared", 20))

    print("LEFT_IMG_FIX_DEPLOY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
