#!/usr/bin/env python3
"""部署桌面协议栈到 Ubuntu VPS 并执行 bootstrap。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
REMOTE_BOOT = f"{R}/scripts/desktop_protocol/bootstrap_ubuntu.sh"


def main() -> int:
    files = [
        (ROOT / "scripts/desktop_protocol/bootstrap_ubuntu.sh", REMOTE_BOOT),
        (ROOT / "protocol/55ws-client/package.json", f"{R}/protocol/55ws-client/package.json"),
        (ROOT / "protocol/55ws-client/watch.js", f"{R}/protocol/55ws-client/watch.js"),
    ]
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        ssh.run(f"mkdir -p {R}/scripts/desktop_protocol {R}/protocol/55ws-client /opt/55m-desktop/logs", 15)
        for local, remote in files:
            ssh.sftp_put(str(local), remote)
        ssh.run(f"sed -i 's/\\r$//' {REMOTE_BOOT} && chmod +x {REMOTE_BOOT}", 12)
        print("=== bootstrap (apt/xfce/wine may take 10-20 min) ===")
        out = ssh.run(f"bash {REMOTE_BOOT} 2>&1", 1800)
        print(out[-8000:] if len(out) > 8000 else out)
        print("=== status ===")
        print(ssh.run(
            "pgrep -a Xtigervnc|head -2; pgrep -a wine|head -3; "
            "ss -lntp|grep -E '5599|5901' || echo no_5599_yet; "
            "tail -20 /opt/55m-desktop/logs/ws-watch.log 2>/dev/null || true; "
            "test -f /opt/55m-desktop/logs/WS_READY.flag && cat /opt/55m-desktop/logs/WS_READY.flag || echo WS_NOT_READY",
            30,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
