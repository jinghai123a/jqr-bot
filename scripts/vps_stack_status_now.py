#!/usr/bin/env python3
"""VPS 栈实况：进程、ADB、内存、最近日志。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        checks = (
            "pgrep -af 'edge_brain|bot_dual_supervisor|spawn_main' | grep -v pgrep || echo NO_BOT_PROCS",
            "adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l",
            f"tail -8 {R}/logs/dual-supervisor.log 2>/dev/null || echo no_log",
            "free -h",
            "ps aux --sort=-%mem | head -8",
        )
        for c in checks:
            print(f"=== {c[:72]} ===")
            print(ssh.run(c, 30))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
