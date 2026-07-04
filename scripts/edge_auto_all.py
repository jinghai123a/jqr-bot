#!/usr/bin/env python3
"""一键：本地测试 + VPS 对齐开源栈（生产=dual_supervisor，非 edge_adb_agent）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
UPLOAD = [
    "requirements-edge.txt",
    "scripts/edge_brain_start.sh",
    "scripts/edge_auto_bootstrap.sh",
    "scripts/edge_adb_connect.sh",
    "scripts/edge_adb_agent_start.sh",
    "scripts/edge_adb_agent.py",
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


def local_tests() -> None:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements-edge.txt")],
    )
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_edge_brain.py", "-q"],
        cwd=str(ROOT),
    )


def vps_auto() -> None:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        ssh.run(f"mkdir -p {R}/edge_brain {R}/w49_core {R}/w49_render {R}/scripts {R}/artifacts {R}/edge_android/settle-left {R}/edge_android/listener-right", 20)
        for rel in UPLOAD:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
        for sh in ("edge_brain_start.sh", "edge_adb_connect.sh", "edge_auto_bootstrap.sh", "edge_adb_agent_start.sh"):
            ssh.run(f"sed -i 's/\\r$//' {R}/scripts/{sh} && chmod +x {R}/scripts/{sh}", 15)
        print(ssh.run(
            f"cd {R} && {R}/.venv/bin/python3 -m pip install -q -r requirements-edge.txt && "
            f"{R}/.venv/bin/python3 -m py_compile scripts/edge_adb_agent.py edge_brain/app.py",
            120,
        ))
        print("=== reconnect dual adb ===")
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -25", 180))
        print(ssh.run("adb devices -l 2>/dev/null | head -10", 15))
        print("=== edge_brain ===")
        print(ssh.run(f"bash {R}/scripts/edge_brain_start.sh", 25))
        print(ssh.run("sleep 2; curl -sf http://127.0.0.1:8790/health; echo", 15))
        print(ssh.run(f"bash {R}/scripts/edge_adb_connect.sh 2>&1", 120))
        print("=== OSS bootstrap (BOT_EDGE_AUTOJS6=0 default) ===")
        print(ssh.run(f"bash {R}/scripts/edge_auto_bootstrap.sh 2>&1 | tail -20", 300))
        print("=== deploy right OSS + reload dual ===")
        print(ssh.run(f"bash {R}/scripts/deploy-listener-oss-stack.sh 2>&1 | tail -15", 300))
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -10", 120))
        print(ssh.run("sleep 2; pgrep -af 'edge_brain|bot_dual_supervisor' | grep -v pgrep", 15))
        print(ssh.run(
            "pgrep -af edge_adb_agent || echo OK_no_edge_adb_agent",
            15,
        ))
        print(ssh.run(
            "adb -P 5038 -s 127.0.0.1:58433 shell echo right_ok; "
            "adb -P 5039 -s 127.0.0.1:52840 shell echo left_ok",
            25,
        ))


def main() -> int:
    local_tests()
    vps_auto()
    print("EDGE_AUTO_ALL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
