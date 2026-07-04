#!/usr/bin/env python3
"""仅重跑 VPS bootstrap + agent（跳过 pytest）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
FILES = [
    "scripts/edge_adb_connect.sh",
    "scripts/edge_auto_bootstrap.sh",
    "scripts/edge_adb_agent_start.sh",
    "scripts/edge_adb_agent.py",
    "edge_android/settle-left/settle_left.js",
    "edge_android/settle-left/edge_config.json",
    "edge_android/listener-right/listener_right.js",
    "edge_android/listener-right/edge_config.json",
]


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        for rel in FILES:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
        for sh in ("edge_adb_connect.sh", "edge_auto_bootstrap.sh", "edge_adb_agent_start.sh"):
            ssh.run(f"sed -i 's/\\r$//' {R}/scripts/{sh} && chmod +x {R}/scripts/{sh}", 15)
        print(ssh.run(f"bash {R}/scripts/edge_auto_bootstrap.sh 2>&1", 600))
        print(ssh.run(f"bash {R}/scripts/edge_adb_agent_start.sh", 20))
        print(ssh.run("tail -5 /home/bot/55chat-bot/logs/edge-adb-agent.log 2>/dev/null", 15))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
