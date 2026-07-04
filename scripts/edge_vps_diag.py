#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH
R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
with VpsSSH(load_vps_config(ROOT)) as ssh:
    print(ssh.run(f"tail -50 {R}/logs/edge-brain.log 2>&1 || echo no_log", 20))
    print(ssh.run(f"{PY} -m pip install -q -r {R}/requirements-edge.txt 2>&1 | tail -3", 120))
    print(ssh.run(f"cd {R} && BOT_ROOT={R} {PY} -c 'import edge_brain.app; print(\"import_ok\")' 2>&1", 30))
    env = f"EDGE_BRAIN_HOST=0.0.0.0 EDGE_BRAIN_PORT=8790 EDGE_BRAIN_JWT_SECRET=required BOT_ROOT={R}"
    print(ssh.run(f"cd {R} && nohup env {env} {PY} -m edge_brain > logs/edge-brain.log 2>&1 & sleep 4; curl -v http://127.0.0.1:8790/health 2>&1 | tail -8", 60))
