#!/usr/bin/env python3
"""排查谁在点退出/Back/Home（VPS 日志+进程）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        print("=== PROCESSES ===")
        print(ssh.run(
            "pgrep -af 'bot_55chat|dual_supervisor|spawn_main|edge_adb|edge_brain|"
            "autojs|watchdog|cloud_dual|recover|vmos|lean' 2>/dev/null | grep -v pgrep | head -35",
            25,
        ))
        print("\n=== CRON ===")
        print(ssh.run("crontab -l 2>/dev/null | head -25", 15))
        print("\n=== SYSTEMD TIMERS ===")
        print(ssh.run("systemctl list-timers --all 2>/dev/null | grep -i vmos", 15))
        print("\n=== BOT LOG (exit/nav/back) last 50 ===")
        print(ssh.run(
            f"grep -E '系统返回|按 Home|大退|force-stop|keyevent|退出|Back|"
            f"文件夹|System Tools|不在群|recover|launch_messenger|温启动|"
            f"boot|关闭叠层|header|左上角|dismiss|看门狗|stay-' "
            f"{R}/logs/bot.log | tail -50",
            30,
        ))
        print("\n=== AUTOJS / AGENT LOG ===")
        print(ssh.run(f"tail -20 {R}/logs/edge-adb-agent.log 2>/dev/null || echo no_agent", 15))
        print("\n=== RIGHT FOCUS ===")
        print(ssh.run(
            "adb -s localhost:58433 shell dumpsys window displays 2>/dev/null | "
            "grep -E 'mCurrentFocus|mFocusedApp' | head -6",
            20,
        ))
        print("\n=== LEFT FOCUS ===")
        print(ssh.run(
            "adb -s localhost:52840 shell dumpsys window displays 2>/dev/null | "
            "grep -E 'mCurrentFocus|mFocusedApp' | head -6",
            20,
        ))
        print("\n=== ENV ===")
        print(ssh.run(
            f"grep -E 'MANUAL_IN_GROUP|ZERO_NAV|EDGE_ADB|EDGE_AUTOJS6|CLICKER_SEND' "
            f"{R}/config/bot-start.env",
            10,
        ))
        print("\n=== RECENT ADB SHELL (if audit) ===")
        print(ssh.run(
            f"grep -E 'input keyevent|force-stop|am start' {R}/logs/bot.log | tail -20",
            20,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
