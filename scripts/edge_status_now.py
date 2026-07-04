#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
with VpsSSH(load_vps_config(ROOT)) as ssh:
    print("=== procs ===")
    print(ssh.run(
        "pgrep -af edge_brain 2>/dev/null; pgrep -af edge_adb_agent 2>/dev/null; "
        "pgrep -af bot_55chat_daemon 2>/dev/null; pgrep -af bot_dual 2>/dev/null",
        20,
    ))
    print("=== listen ===")
    print(ssh.run("ss -tlnp 2>/dev/null | grep 8790 || echo no_8790", 15))
    print("=== agent log ===")
    print(ssh.run(f"tail -8 {R}/logs/edge-adb-agent.log 2>/dev/null || echo no_agent_log", 15))
