#!/usr/bin/env python3
"""VMOS OpenAPI 续期隧道 + 双 ADB 重连。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH
from bot_ops.vps_ports import dual_adb_online, dual_adb_ports

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"


def main() -> int:
    rport, lport = dual_adb_ports(ROOT)
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        print(f"=== ports listener={rport} clicker={lport} ===")
        ssh.run(
            "pkill -9 -f vmos-refresh-tunnels.py 2>/dev/null || true; "
            f"rm -f {R}/logs/.vmos-refresh.lock; echo cleared",
            20,
        )
        print(
            ssh.run(
                f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --expire-if-needed --reconnect 2>&1 | tail -40",
                300,
            )
        )
        time.sleep(5)
        out = ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 20)
        print(out)
        ok = dual_adb_online(out, rport, lport)
        if ok:
            print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -8", 300))
            time.sleep(12)
            print(
                ssh.run(
                    f"grep -E 'open_after_settle|批量发图|capture-ipc.*done' "
                    f"{R}/logs/dual-supervisor.log | tail -10",
                    25,
                )
            )
            print(
                ssh.run(
                    f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
                    f"{PY} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1 | grep state=",
                    90,
                )
            )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
