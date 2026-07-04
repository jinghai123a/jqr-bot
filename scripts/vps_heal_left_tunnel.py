#!/usr/bin/env python3
"""强制重建左机隧道并验收双 ADB。"""
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
LOG = f"{R}/logs/dual-supervisor.log"
PY = f"{R}/.venv/bin/python3"


def main() -> int:
    rport, lport = dual_adb_ports(ROOT)
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        print(f"=== ports listener={rport} clicker={lport} ===")
        print(
            ssh.run(
                "pkill -9 -f vmos-refresh-tunnels.py 2>/dev/null || true; "
                f"rm -f {R}/logs/.vmos-refresh.lock; "
                "adb disconnect emulator-5554 2>/dev/null || true; echo ok",
                20,
            )
        )
        print(ssh.run(f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -25", 120))
        time.sleep(3)
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -20", 180))
        ok = False
        for i in range(10):
            out = ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 20)
            print(f"poll {i + 1}:\n{out}")
            if dual_adb_online(out, rport, lport):
                ok = True
                break
            time.sleep(8)
        if not ok:
            print(ssh.run(
                f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --side left --reconnect 2>&1 | tail -30",
                180,
            ))
            print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -12", 120))
            out = ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 20)
            print(out)
            ok = dual_adb_online(out, rport, lport)
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -10", 300))
        time.sleep(10)
        print(ssh.run(f"grep -E 'open_after_settle|capture-ipc|批量发图' {LOG} | tail -12", 25))
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
