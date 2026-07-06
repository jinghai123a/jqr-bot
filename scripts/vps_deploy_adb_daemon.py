#!/usr/bin/env python3
"""部署 VMOS ADB 动态续期守护到 VPS 并立即启动。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
UPLOAD = (
    "bot_tunnel/daemon.py",
    "bot_tunnel/refresh.py",
    "bot_tunnel/__init__.py",
    "bot_tunnel/expire_schedule.py",
    "scripts/vmos_adb_daemon.py",
    "scripts/vmos_adb_daemon_start.sh",
    "scripts/watch-adb-tunnels.sh",
    "scripts/vps_minimal_cron.sh",
    "scripts/vmos_api/transport.py",
    "scripts/vmos_api/client.py",
)


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        for rel in UPLOAD:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
                print(f"uploaded {rel}")
        ssh.run(
            f"chmod +x {R}/scripts/vmos_adb_daemon_start.sh {R}/scripts/watch-adb-tunnels.sh "
            f"{R}/scripts/vps_minimal_cron.sh; sed -i 's/\\r$//' {R}/scripts/vmos_adb_daemon_start.sh",
            15,
        )
        print(ssh.run(f"bash {R}/scripts/vps_minimal_cron.sh 2>&1 | tail -12", 30))
        print(ssh.run(f"bash {R}/scripts/vmos_adb_daemon_start.sh restart 2>&1", 120))
        print(ssh.run(f"bash {R}/scripts/vmos_adb_daemon_start.sh status 2>&1", 60))
        print(ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
