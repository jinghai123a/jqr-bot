#!/usr/bin/env python3
"""左机隧道重连 + finance.db 端口对齐 + reload。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH
from bot_ops.vps_ports import dual_adb_ports

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"


def main() -> int:
    _rport, lport = dual_adb_ports(ROOT)
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        print(ssh.run(f"{PY} {R}/scripts/patch_speed_env.py 2>&1", 30))
        print(ssh.run(f"grep -o 'localhost:[0-9]*' {R}/finance.db | sort -u", 15))
        ssh.run(f"pkill -f 'ssh.*{lport}:' 2>/dev/null || true", 10)
        time.sleep(2)
        print(ssh.run(f"bash {R}/scripts/tunnel-left.sh 2>&1", 120))
        time.sleep(3)
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -20", 180))
        print(ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 20))
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -12", 300))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
