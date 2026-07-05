#!/usr/bin/env python3
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
    remote = ROOT / "scripts" / "vps_dump_clicker_ui_remote.py"
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        ssh.sftp_put(str(ROOT / "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
        ssh.sftp_put(str(remote), f"{R}/scripts/vps_dump_clicker_ui_remote.py")
        print(ssh.run(f"cd {R} && {PY} scripts/vps_dump_clicker_ui_remote.py", 90))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
