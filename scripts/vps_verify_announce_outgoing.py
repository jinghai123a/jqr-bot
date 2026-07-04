#!/usr/bin/env python3
"""部署 verify_group_announce_outgoing 到 APS 并执行验收。"""
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
    lport = cfg.clicker_adb_port
    rport = cfg.listener_adb_port
    with VpsSSH(cfg) as ssh:
        remote_ports = ssh.run(
            f"grep -E '^BOT_CLICKER_ADB_PORT=|^BOT_LISTENER_ADB_PORT=' {R}/config/bot-start.env 2>/dev/null",
            15,
        )
        for line in remote_ports.splitlines():
            if line.startswith("BOT_CLICKER_ADB_PORT="):
                lport = line.split("=", 1)[1].strip()
            elif line.startswith("BOT_LISTENER_ADB_PORT="):
                rport = line.split("=", 1)[1].strip()
        for rel in FILES:
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
        print(ssh.run(f"bash {R}/scripts/edge_brain_start.sh 2>&1 | tail -3", 30))
        out = ssh.run(
            f"cd {R} && {py} scripts/verify_group_announce_outgoing.py "
            f"--left 127.0.0.1:{lport} --right 127.0.0.1:{rport} 2>&1",
            180,
        )
        print(out)
        return 0 if "verdict=PASS" in out or "PASS" in out.split("verdict=")[-1][:20] else 1


if __name__ == "__main__":
    raise SystemExit(main())
