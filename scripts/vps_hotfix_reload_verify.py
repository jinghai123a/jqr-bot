#!/usr/bin/env python3
"""热更新 daemon + reload 双进程并验收左机公告/发图日志。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

PATS = (
    "sender-bot-3",
    "左机公告发送成功",
    "直接入队新一局",
    "队列出队 kind=open_after_settle",
    "封盘提醒 rid",
    "capture-ipc] done",
)


def main() -> int:
    cfg = load_vps_config(ROOT)
    r = cfg.bot_root
    log = f"{r}/logs/dual-supervisor.log"
    with VpsSSH(cfg) as ssh:
        ssh.sftp_put(str(ROOT / "bot_55chat_daemon.py"), f"{r}/bot_55chat_daemon.py")
        print(ssh.run(f"bash {r}/scripts/reload-dual-workers.sh 2>&1 | tail -12", 300))
        time.sleep(100)
        for pat in PATS:
            print(f"\n=== {pat} ===")
            print(ssh.run(f"grep -E '{pat}' {log} 2>/dev/null | tail -6", 25) or "(none)")
        print("\n=== procs ===")
        print(ssh.run("pgrep -af 'bot_dual_supervisor|edge_brain' | grep -v pgrep", 15))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
