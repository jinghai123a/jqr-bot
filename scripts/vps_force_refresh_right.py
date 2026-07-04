#!/usr/bin/env python3
"""强制 VPS 右 pad OpenAPI 刷新并验双机 android_id 不同。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
LOG = f"{R}/logs/refresh-right-force.log"


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        ssh.run(
            "pkill -9 -f vmos-refresh-tunnels.py 2>/dev/null; sleep 2; "
            f"rm -f {R}/logs/.vmos-refresh.lock; echo killed",
            20,
        )
        print("=== pad status ===")
        print(ssh.run(f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --status 2>&1", 90))

        cmd = f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --reconnect --side right"
        print("=== force refresh right ===")
        print(ssh.run_nohup(cmd, log_path=LOG, max_wait=540.0))

        print("=== reconnect ===")
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -12", 120))

        print("=== device ids ===")
        for p in ("52840", "58433"):
            aid = ssh.run(f"adb -s localhost:{p} shell settings get secure android_id 2>/dev/null", 20).strip()
            model = ssh.run(f"adb -s localhost:{p} shell getprop ro.product.model 2>/dev/null", 20).strip()
            print(f"  {p}: model={model} id={aid}")

        print("=== visual ===")
        print(ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"{PY} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1",
            120,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
