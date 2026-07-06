#!/usr/bin/env python3
"""扫描 VPS 上仍引用旧 clicker 端口的配置。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH
from bot_ops.vps_ports import dual_adb_ports

R = "/home/bot/55chat-bot"


def main() -> int:
    _rport, lport = dual_adb_ports(ROOT)
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        print(ssh.run(
            f"grep -r '52840\\|50719' {R}/config {R}/finance.db 2>/dev/null | head -25 || echo clean",
            30,
        ))
        print(ssh.run(
            f"python3 -c \"import json; d=json.load(open('{R}/finance.db')); "
            f"bots=[x for x in d.get('bots',[]) if isinstance(x,dict)]; "
            f"print([(b.get('id'),b.get('adbHost')) for b in bots])\"",
            20,
        ))
        print(f"expected clicker port: {lport}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
