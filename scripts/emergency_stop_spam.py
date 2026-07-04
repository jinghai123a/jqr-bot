#!/usr/bin/env python3
"""紧急止血：停 AutoJs6、清输入框、重载双进程。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PKG = "org.autojs.autojs6"
LEFT = "adb -P 5039 -s 127.0.0.1:52840"
RIGHT = "adb -P 5038 -s 127.0.0.1:58433"


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        print("=== stop AutoJs6 + edge_adb ===")
        for adb in (LEFT, RIGHT):
            print(ssh.run(
                f"{adb} shell am force-stop {PKG} 2>/dev/null; "
                f"{adb} shell input keyevent 4 2>/dev/null; "
                f"{adb} shell input keyevent 111 2>/dev/null; "
                "true",
                25,
            ))
        print(ssh.run("pkill -f edge_adb_agent.py 2>/dev/null || true", 10))

        print("=== clear composer (ESC x3) ===")
        for adb in (LEFT, RIGHT):
            print(ssh.run(
                f"{adb} shell input keyevent 4; {adb} shell input keyevent 4; "
                f"{adb} shell input keyevent 4; sleep 1; true",
                20,
            ))

        print("=== deploy latest daemon ===")
        ssh.sftp_put(str(ROOT / "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
        ssh.sftp_put(
            str(ROOT / "edge_android/listener-right/listener_right.js"),
            f"{R}/edge_android/listener-right/listener_right.js",
        )
        print(ssh.run(
            f"{RIGHT} push {R}/edge_android/listener-right/listener_right.js "
            "/sdcard/Scripts/w49-listener-right/listener_right.js 2>&1",
            30,
        ))

        print("=== reload ===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -10", 180))

    print("EMERGENCY_STOP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
