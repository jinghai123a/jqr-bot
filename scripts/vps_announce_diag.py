#!/usr/bin/env python3
"""APS 公告链诊断：端口、adb、supervisor 日志、OUT 验收。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402

FILES = (
    "bot_ops/announce_audit.py",
    "scripts/verify_group_announce_outgoing.py",
)


def main() -> int:
    cfg = load_vps_config(ROOT)
    R = cfg.bot_root
    py = f"{R}/.venv/bin/python3"
    with VpsSSH(cfg) as ssh:
        for rel in FILES:
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
        ports = ssh.run(
            f"grep -E '^BOT_CLICKER_ADB_PORT=|^BOT_LISTENER_ADB_PORT=' {R}/config/bot-start.env",
            15,
        )
        print("=== ports ===\n", ports)
        print("=== adb ===\n", ssh.run("adb devices -l; adb -P 5038 devices -l; adb -P 5039 devices -l", 25))
        print("=== procs ===\n", ssh.run("pgrep -af 'edge_brain|dual_supervisor|bot_55chat' | grep -v pgrep", 15))
        print("=== announce log ===\n", ssh.run(
            f"grep -E '公告|开局|封盘|发送完成|announce' {R}/logs/dual-supervisor.log 2>/dev/null | tail -20",
            20,
        ))
        lport, rport = cfg.clicker_adb_port, cfg.listener_adb_port
        for line in ports.splitlines():
            if line.startswith("BOT_CLICKER_ADB_PORT="):
                lport = line.split("=", 1)[1].strip()
            elif line.startswith("BOT_LISTENER_ADB_PORT="):
                rport = line.split("=", 1)[1].strip()
        print("=== verify ===\n", ssh.run(
            f"cd {R} && {py} scripts/verify_group_announce_outgoing.py "
            f"--left 127.0.0.1:{lport} --right 127.0.0.1:{rport} 2>&1",
            180,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
