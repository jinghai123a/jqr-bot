#!/usr/bin/env python3
"""APS 部署续跑：edge_brain 已起时从 ADB connect + bootstrap 继续。"""
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
        local = ROOT / "scripts" / "edge_adb_connect.sh"
        ssh.sftp_put(str(local), f"{R}/scripts/edge_adb_connect.sh")
        ssh.run(f"sed -i 's/\\r$//' {R}/scripts/edge_adb_connect.sh && chmod +x {R}/scripts/edge_adb_connect.sh", 15)

        print("=== reconnect dual adb (180s) ===")
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -30", 240))
        print(ssh.run("adb devices -l 2>/dev/null | head -12", 20))

        print("=== edge_adb_connect ===")
        print(ssh.run(f"bash {R}/scripts/edge_adb_connect.sh 2>&1", 150))

        print("=== edge_auto_bootstrap ===")
        print(ssh.run(f"bash {R}/scripts/edge_auto_bootstrap.sh 2>&1 | tail -25", 360))

        print("=== edge_adb_agent ===")
        print(ssh.run(f"bash {R}/scripts/edge_adb_agent_start.sh", 25))
        print(ssh.run("sleep 2; pgrep -af 'edge_brain|edge_adb_agent' | grep -v pgrep", 15))
        print(ssh.run(f"tail -12 {R}/logs/edge-adb-agent.log 2>/dev/null || echo no_agent_log", 15))
        print(ssh.run("curl -sf http://127.0.0.1:8790/health; echo", 15))
        print(ssh.run(
            "adb -P 5038 -s 127.0.0.1:58433 shell echo right_ok 2>&1; "
            "adb -P 5039 -s 127.0.0.1:52840 shell echo left_ok 2>&1",
            40,
        ))

    print("APS_RESUME_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
