#!/usr/bin/env python3
"""SSH 修复右机 LISTENER 隧道 :58433。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        print("=== tunnel-right ===")
        print(ssh.run(f"bash {R}/scripts/tunnel-right.sh 2>&1 | tail -20", 120))
        print("=== vmos refresh right ===")
        print(ssh.run(
            f"cd {R} && python3 {R}/scripts/vmos-refresh-tunnels.py --reconnect --side right 2>&1 | tail -25",
            180,
        ))
        print("=== reconnect ===")
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -20", 240))
        print(ssh.run("ss -tlnp | grep -E '58433|52840' || true", 15))
        print(ssh.run("adb devices -l", 15))
        print(ssh.run(f"bash {R}/scripts/edge_adb_connect.sh 2>&1", 120))
        print(ssh.run(
            "adb -P 5038 -s 127.0.0.1:58433 shell echo right_ok 2>&1; "
            "adb -P 5039 -s 127.0.0.1:52840 shell echo left_ok 2>&1",
            40,
        ))
        # Right AutoJs6 if right is up
        print(ssh.run(
            f"adb -P 5038 -s 127.0.0.1:58433 install -r -g {R}/artifacts/autojs6-arm64.apk 2>&1 | tail -3",
            120,
        ))
        print(ssh.run(
            f"adb -P 5038 -s 127.0.0.1:58433 push {R}/edge_android/listener-right/listener_right.js "
            "/sdcard/Scripts/w49-listener-right/listener_right.js 2>&1",
            60,
        ))
    print("HEAL_RIGHT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
