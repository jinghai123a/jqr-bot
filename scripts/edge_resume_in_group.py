#!/usr/bin/env python3
"""W49 手动进群后：停干扰项 + 接上断点（不自动导航、不杀核心功能）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
UPLOAD = (
    "bot_55chat_daemon.py",
    "bot_ops/nav_guard.py",
    "config/55m-knowledge/ui-pages.json",
    "scripts/vmos_visual_monitor.py",
)


def main() -> int:
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_nav_guard.py", "tests/test_edge_brain.py", "-q"],
        cwd=str(ROOT),
    )
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        print("=== 停干扰项 ===")
        print(ssh.run(
            "pkill -f edge_adb_agent.py 2>/dev/null; "
            "pkill -f cloud_dual_watch 2>/dev/null; "
            "systemctl stop vmos-dual-watchdog.timer 2>/dev/null; "
            "systemctl disable vmos-dual-watchdog.timer 2>/dev/null; "
            "crontab -l 2>/dev/null | grep -v vmos-dual-watchdog | grep -v cloud_dual_watch | crontab - 2>/dev/null; "
            "echo interference_stopped",
            30,
        ))

        for rel in UPLOAD:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel}")

        print("=== env: 手动进群模式 ===")
        for kv in (
            "BOT_MANUAL_IN_GROUP=1",
            "BOT_EDGE_ADB_AGENT=0",
            "BOT_LISTENER_ZERO_NAV=1",
        ):
            k, v = kv.split("=", 1)
            print(ssh.run(
                f"grep -q '^{k}=' {R}/config/bot-start.env 2>/dev/null && "
                f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || "
                f"echo '{k}={v}' >> {R}/config/bot-start.env",
                15,
            ))

        print(ssh.run(f"{R}/.venv/bin/python3 -m py_compile {R}/bot_55chat_daemon.py", 45))

        print("=== reload workers（不跑 bootstrap/不回群）===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -15", 300))

        print("=== 验群（只读）===")
        print(ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"python3 {R}/scripts/vmos_visual_monitor.py --both --once 2>&1",
            90,
        ))
        print(ssh.run(
            "pgrep -af 'edge_brain|bot_dual_supervisor|spawn_main|edge_adb_agent' | grep -v pgrep; "
            "curl -sf http://127.0.0.1:8790/health; echo",
            20,
        ))

    print("EDGE_RESUME_IN_GROUP_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
