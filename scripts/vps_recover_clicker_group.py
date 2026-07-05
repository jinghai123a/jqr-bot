#!/usr/bin/env python3
"""清除 VPS 上卡死的 capture-ipc 队列并强制左机回群。"""
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
        ssh.sftp_put(str(ROOT / "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
        print("=== reload workers ===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -8", 300))
        print("=== purge capture-ipc (inflight+pending+terminal stale) ===")
        print(
            ssh.run(
                f"rm -f {R}/data/capture_ipc/inflight/*.json "
                f"{R}/data/capture_ipc/pending/*.json 2>/dev/null; "
                f"find {R}/data/capture_ipc/terminal -name '*.json' -mmin +30 -delete 2>/dev/null; "
                f"echo cleared",
                20,
            )
        )
        print("=== heal clicker in group ===")
        print(
            ssh.run(
                f"set -a; source {R}/config/bot-start.env 2>/dev/null; set +a; "
                f"cd {R} && {PY} {R}/scripts/vps_heal_clicker_once.py 2>&1",
                180,
            )
        )
        print(
            ssh.run(
                f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
                f"{PY} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1 | grep state=",
                90,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
