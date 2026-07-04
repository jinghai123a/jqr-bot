#!/usr/bin/env python3
"""部署 edge 坐标同步 + edge_brain open_text 到 APS。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
UPLOAD = [
    "edge_brain/app.py",
    "config/pinned-coords.json",
    "edge_android/settle-left/settle_left.js",
    "edge_android/settle-left/edge_config.json",
    "edge_android/listener-right/listener_right.js",
    "edge_android/listener-right/edge_config.json",
    "scripts/sync_edge_android_coords.py",
]


def main() -> int:
    subprocess = __import__("subprocess")
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "sync_edge_android_coords.py")])

    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        for rel in UPLOAD:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
        print("=== edge_brain restart ===")
        print(ssh.run(f"bash {R}/scripts/edge_brain_start.sh", 25))
        print(ssh.run("sleep 2; curl -sf http://127.0.0.1:8790/health; echo", 10))
        print("=== push AutoJs6 scripts ===")
        print(ssh.run(f"bash {R}/scripts/edge_adb_connect.sh 2>&1", 90))
        adb_l = (
            f"adb -P 5039 -s 127.0.0.1:52840 push {R}/edge_android/settle-left/settle_left.js "
            "/sdcard/Scripts/w49-settle-left/settle_left.js && "
            f"adb -P 5039 -s 127.0.0.1:52840 push {R}/edge_android/settle-left/edge_config.json "
            "/sdcard/Scripts/w49-settle-left/edge_config.json"
        )
        adb_r = (
            f"adb -P 5038 -s 127.0.0.1:58433 push {R}/edge_android/listener-right/listener_right.js "
            "/sdcard/Scripts/w49-listener-right/listener_right.js && "
            f"adb -P 5038 -s 127.0.0.1:58433 push {R}/edge_android/listener-right/edge_config.json "
            "/sdcard/Scripts/w49-listener-right/edge_config.json"
        )
        print(ssh.run(adb_l, 60))
        print(ssh.run(adb_r, 60))
        print(ssh.run(
            "curl -sf -H 'Authorization: Bearer w49-edge-local' http://127.0.0.1:8790/edge/open-job; echo",
            10,
        ))
    print("EDGE_COORDS_DEPLOY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
