#!/usr/bin/env python3
"""从 APS/VPS 同步生产 parity 文件到本机（board_capture 等）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
SYNC = [
    "board_capture.py",
    "config/pinned-coords.json",
    "config/bot-start.env",
]


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        for rel in SYNC:
            remote = f"{R}/{rel}"
            local = ROOT / rel
            local.parent.mkdir(parents=True, exist_ok=True)
            try:
                ssh.sftp_get(remote, str(local))
                print(f"OK {rel}")
            except Exception as ex:
                print(f"SKIP {rel}: {ex}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
