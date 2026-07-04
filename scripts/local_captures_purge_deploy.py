#!/usr/bin/env python3
"""本地触发：上传清理脚本 + 清 captures + 卸无用 App + 装 cron。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
UPLOAD = (
    "scripts/vps_captures_cleanup.py",
    "scripts/purge_unused_apps.py",
    "scripts/vps_minimal_cron.sh",
)


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        for rel in UPLOAD:
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
        ssh.run(f"chmod +x {R}/scripts/vps_minimal_cron.sh", 10)
        print("=== captures cleanup now ===")
        print(ssh.run(f"cd {R} && {PY} scripts/vps_captures_cleanup.py", 60))
        print("=== purge unused apps (no restart) ===")
        print(ssh.run(
            f"cd {R} && {PY} scripts/purge_unused_apps.py --no-restart 2>&1",
            300,
        ))
        print("=== install cron ===")
        print(ssh.run(f"bash {R}/scripts/vps_minimal_cron.sh 2>&1", 30))
        print("=== disk/mem after ===")
        print(ssh.run(
            f"du -sh {R}/data/captures {R}/data 2>/dev/null; free -h | head -2; "
            f"adb -s localhost:52840 shell free -h 2>/dev/null | head -3; "
            f"adb -s localhost:58433 shell free -h 2>/dev/null | head -3",
            30,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
