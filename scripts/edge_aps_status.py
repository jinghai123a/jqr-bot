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
    for label, cmd, t in [
        ("health", "curl -sf http://127.0.0.1:8790/health; echo", 10),
        ("procs", "pgrep -af 'edge_brain|edge_adb_agent' | grep -v pgrep", 10),
        ("tunnels", "ss -tlnp 2>/dev/null | grep 58433; ss -tlnp 2>/dev/null | grep 52840", 10),
        ("left", "adb -P 5039 -s 127.0.0.1:52840 shell echo left_ok 2>&1", 20),
        ("right", "adb -P 5038 -s 127.0.0.1:58433 shell echo right_ok 2>&1", 20),
        ("agent", f"tail -4 {R}/logs/edge-adb-agent.log 2>/dev/null", 10),
    ]:
        print(f"=== {label} ===")
        print(ssh.run(cmd, t))
