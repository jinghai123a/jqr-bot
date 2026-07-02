#!/usr/bin/env python3
"""部署 P0 发图验真 + P1 open 旁路 + P2 SRE snippet 抑制。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
SYNC = [
    "bot_55chat_daemon.py",
    "bot_ops/sre_self_heal.py",
    "bot_ops/physical_feedback.py",
]


def main() -> int:
    cfg = load_vps_config(ROOT, prompt_password=False)
    with VpsSSH(cfg) as ssh:
        for rel in SYNC:
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
            print("synced", rel)
        print("=== env patch ===")
        print(
            ssh.run(
                f"grep -q BOT_PHYSICAL_OPEN_SNIPPET_P0=0 {R}/config/bot-start.env 2>/dev/null "
                f"|| echo BOT_PHYSICAL_OPEN_SNIPPET_P0=0 >> {R}/config/bot-start.env",
                15,
            )
        )
        print("=== py_compile ===")
        for rel in SYNC:
            print(ssh.run(f"{R}/.venv/bin/python3 -m py_compile {R}/{rel}", 30))
        print("=== reload dual workers ===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1", 180))
        time.sleep(10)
        print("=== spawn check ===")
        print(ssh.run("pgrep -af 'spawn_main|bot_dual_supervisor' | head -6", 15))
        print("=== recent logs ===")
        print(
            ssh.run(
                f"grep -E '验真|快验|capture-ipc|spawn|SELF-HEAL|reload' "
                f"{R}/logs/dual-supervisor.log 2>/dev/null | tail -25",
                20,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
