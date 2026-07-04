#!/usr/bin/env python3
"""部署 edge_brain 到 VPS + 冒烟 curl。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
PORT = 8790

UPLOAD = [
    "requirements-edge.txt",
    "scripts/edge_brain_start.sh",
    "edge_brain/__init__.py",
    "edge_brain/__main__.py",
    "edge_brain/app.py",
    "edge_brain/config.py",
    "edge_brain/pubsub.py",
    "edge_brain/state.py",
    "w49_core/__init__.py",
    "w49_core/draw.py",
    "w49_core/timing.py",
    "w49_render/__init__.py",
    "w49_render/png_bundle.py",
    "edge_android/settle-left/settle_left.js",
    "edge_android/settle-left/edge_config.json",
    "edge_android/listener-right/listener_right.js",
    "edge_android/listener-right/edge_config.json",
]


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        ssh.run(f"mkdir -p {R}/edge_brain {R}/w49_core {R}/w49_render {R}/edge_android/settle-left {R}/edge_android/listener-right", 20)
        for rel in UPLOAD:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
                print("uploaded", rel)
        print(ssh.run(
            f"cd {R} && {PY} -m pip install -q -r requirements-edge.txt && "
            f"{PY} -m py_compile edge_brain/app.py w49_core/draw.py w49_render/png_bundle.py",
            120,
        ))
        print(ssh.run(
            f"sed -i 's/\\r$//' {R}/scripts/edge_brain_start.sh && "
            f"chmod +x {R}/scripts/edge_brain_start.sh && bash {R}/scripts/edge_brain_start.sh",
            25,
        ))
        print(ssh.run(f"sleep 2; curl -sf http://127.0.0.1:{PORT}/health; echo", 20))
        print(ssh.run(
            f"curl -sf -H 'Authorization: Bearer w49-edge-local' http://127.0.0.1:{PORT}/edge/timeline | head -c 400; echo",
            30,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
