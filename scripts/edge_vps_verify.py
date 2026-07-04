#!/usr/bin/env python3
"""VPS：edge_brain 进程 + API 验收 + 双机 edge_config 路径确认。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PORT = 8790


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        print(ssh.run(
            f"sed -i 's/\\r$//' {R}/scripts/edge_brain_start.sh && bash {R}/scripts/edge_brain_start.sh",
            25,
        ))
        print(ssh.run(f"sleep 2; curl -sf http://127.0.0.1:{PORT}/health || echo health_fail", 20))
        print(ssh.run(
            f"curl -sf -H 'Authorization: Bearer w49-edge-local' "
            f"'http://127.0.0.1:{PORT}/edge/timeline' | head -c 500; echo",
            30,
        ))
        print(ssh.run(
            f"pgrep -af edge_brain | grep -v pgrep; tail -5 {R}/logs/edge-brain.log 2>/dev/null",
            20,
        ))
        print(ssh.run(
            f"adb -P 5038 devices 2>/dev/null | head -3; adb -P 5039 devices 2>/dev/null | head -3",
            20,
        ))
        print(ssh.run(f"ls -la {R}/edge_android/settle-left/ {R}/edge_android/listener-right/", 20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
