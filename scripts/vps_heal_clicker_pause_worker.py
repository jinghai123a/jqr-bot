#!/usr/bin/env python3
"""暂停左 worker → heal → visual → reload。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        for rel in (
            "bot_55chat_daemon.py",
            "scripts/vps_heal_clicker_once.py",
            "scripts/production_deploy_run.py",
        ):
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
        print(ssh.run(
            "pkill -15 -f spawn_main 2>/dev/null || true; sleep 3; echo paused",
            15,
        ))
        print(ssh.run(
            f"set -a; source {R}/config/bot-start.env 2>/dev/null; set +a; "
            f"cd {R} && {PY} scripts/vps_heal_clicker_once.py",
            200,
        ))
        print(ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"{PY} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1 | grep state=",
            90,
        ))
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -6", 240))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
