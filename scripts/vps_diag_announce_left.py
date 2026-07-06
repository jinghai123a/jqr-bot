#!/usr/bin/env python3
"""左机公告链 VPS 诊断：线程、日志、BOT_CLICKER_SEND_ANNOUNCE。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

PATS = (
    "announce-bot-3",
    "sender-bot-3",
    "左机禁止",
    "drain serial",
    "入队三图",
    "队列出队 kind=",
    "封盘提醒",
    "封盘公告",
    "开局公告",
    "三图后新一局",
    "直接入队新一局",
    "open_after_settle",
    "左机公告发送成功",
    "公告发送失败",
    "capture-ipc.*done",
)


def main() -> int:
    cfg = load_vps_config(ROOT)
    r = cfg.bot_root
    with VpsSSH(cfg) as ssh:
        print("=== logs dir ===")
        print(ssh.run(f"ls -la {r}/logs/ 2>/dev/null | tail -20", 20))
        for log in (
            f"{r}/logs/supervisor.log",
            f"{r}/logs/bot-daemon.log",
            f"{r}/logs/dual-supervisor.log",
        ):
            print(f"\n=== tail {log} ===")
            print(ssh.run(f"test -f {log} && tail -25 {log} || echo missing", 25))
        print(ssh.run(f"grep BOT_CLICKER_SEND_ANNOUNCE {r}/config/bot-start.env 2>/dev/null || echo missing", 15))
        for pat in PATS:
            print(f"\n=== {pat} ===")
            out = ssh.run(f"grep -rE '{pat}' {r}/logs/ 2>/dev/null | tail -8", 30)
            print(out.strip() or "(none)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
