#!/usr/bin/env python3
"""APS 自动修复公告链：关 MANUAL_IN_GROUP、重连双隧道、reload supervisor。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402

R = "/home/bot/55chat-bot"


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        print("=== patch MANUAL_IN_GROUP=0 ===")
        print(ssh.run(
            f"grep -q '^BOT_MANUAL_IN_GROUP=' {R}/config/bot-start.env 2>/dev/null && "
            f"sed -i 's/^BOT_MANUAL_IN_GROUP=.*/BOT_MANUAL_IN_GROUP=0/' {R}/config/bot-start.env || "
            f"echo 'BOT_MANUAL_IN_GROUP=0' >> {R}/config/bot-start.env; "
            f"grep BOT_MANUAL_IN_GROUP {R}/config/bot-start.env",
            20,
        ))
        print("=== tunnel right ===")
        print(ssh.run(f"bash {R}/scripts/tunnel-right.sh 2>&1 | tail -20", 120))
        print("=== adb ===")
        print(ssh.run("adb devices -l", 20))
        print(ssh.run("ss -tlnp 2>/dev/null | grep 58433 || echo NO_58433", 15))
        print("=== reload supervisor ===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -8", 240))
        print("=== recover right group ===")
        py = f"{R}/.venv/bin/python3"
        print(ssh.run(
            f"cd {R} && BOT_MANUAL_IN_GROUP=0 {py} bot_55chat_daemon.py --recover-group 127.0.0.1:58433 2>&1 | tail -5",
            90,
        ))
        import time
        time.sleep(8)
        print("=== verify ===")
        print(ssh.run(
            f"cd {R} && {py} scripts/verify_group_announce_outgoing.py "
            f"--left 127.0.0.1:52840 --right 127.0.0.1:58433 2>&1",
            180,
        ))
        print("=== announce log tail ===")
        print(ssh.run(f"grep -E '公告|发送完成|跳过公告|draft' {R}/logs/dual-supervisor.log | tail -12", 20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
