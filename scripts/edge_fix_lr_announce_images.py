#!/usr/bin/env python3
"""修复：锁定 §4 公告 + b64 灌字 + 禁图失败发 open；部署 daemon 并 reload。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
UPLOAD = [
    "bot_55chat_daemon.py",
    "config/pinned-coords.json",
    "config/55m-knowledge/announce-templates.json",
]


def main() -> int:
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_announce_locked.py", "tests/test_edge_brain.py", "-q"],
        cwd=str(ROOT),
    )
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        for rel in UPLOAD:
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
        ssh.run(
            f"grep -q '^BOT_ANNOUNCE_LOCKED=' {R}/config/bot-start.env 2>/dev/null || "
            f"echo 'BOT_ANNOUNCE_LOCKED=1' >> {R}/config/bot-start.env",
            15,
        )
        ssh.run(
            f"grep -q '^BOT_OPEN_FALLBACK_SEC=' {R}/config/bot-start.env 2>/dev/null || "
            f"echo 'BOT_OPEN_FALLBACK_SEC=0' >> {R}/config/bot-start.env",
            15,
        )
        print(ssh.run(f"{R}/.venv/bin/python3 -m py_compile {R}/bot_55chat_daemon.py", 60))
        print("=== models ===")
        print(
            ssh.run(
                "echo RIGHT=; adb -P 5038 -s 127.0.0.1:58433 shell getprop ro.product.model; "
                "echo LEFT=; adb -P 5039 -s 127.0.0.1:52840 shell getprop ro.product.model",
                25,
            )
        )
        print("=== reload dual ===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -15", 300))
        print(ssh.run(f"grep -E '型号|b64|capture-ipc|左机 CLICKER' {R}/logs/dual-supervisor.log | tail -8", 20))
    print("EDGE_FIX_LR_ANNOUNCE_IMAGES_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
