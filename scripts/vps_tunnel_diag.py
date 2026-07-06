#!/usr/bin/env python3
"""诊断双机隧道状态。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH
from bot_ops.vps_ports import dual_adb_ports

R = "/home/bot/55chat-bot"


def main() -> int:
    rport, lport = dual_adb_ports(ROOT)
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        for p in (
            f"cat {R}/config/tunnel-left.env 2>/dev/null | head -12",
            f"tail -15 {R}/logs/tunnel-left.log 2>/dev/null",
            f"tail -8 {R}/logs/tunnel-watch.log 2>/dev/null",
            f"adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l",
            f"grep -E 'refresh|left|{lport}|banned|Permission' {R}/logs/vmos-refresh.log 2>/dev/null | tail -15 || echo no_vmos_log",
            f"grep BOT_CLICKER_ADB_PORT {R}/config/bot-start.env 2>/dev/null",
        ):
            print(f"=== {p[:60]} ===")
            print(ssh.run(p, 25))
        print(f"=== expected ports listener={rport} clicker={lport} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
