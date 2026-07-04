#!/usr/bin/env python3
"""对齐开源栈到 APS 生产：右机 OSS + dual_supervisor；禁双执行器。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
MATRIX = ROOT / "config/55m-knowledge/executor-matrix.json"


def local_validate() -> None:
    data = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert "dual_supervisor" in data["modes"]
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_edge_brain.py", "tests/test_edge_android_coords.py", "-q"],
        cwd=str(ROOT),
    )


def vps_align() -> None:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        ssh.run(f"mkdir -p {R}/config/55m-knowledge", 15)
        ssh.sftp_put(str(MATRIX), f"{R}/config/55m-knowledge/executor-matrix.json")
        ssh.sftp_put(
            str(ROOT / "config/55m-knowledge/oss-stack.json"),
            f"{R}/config/55m-knowledge/oss-stack.json",
        )
        ssh.sftp_put(
            str(ROOT / "scripts/edge_auto_bootstrap.sh"),
            f"{R}/scripts/edge_auto_bootstrap.sh",
        )
        ssh.run(f"sed -i 's/\\r$//' {R}/scripts/edge_auto_bootstrap.sh && chmod +x {R}/scripts/edge_auto_bootstrap.sh", 15)

        env_patch = (
            "grep -q '^BOT_EDGE_AUTOJS6=' {R}/config/bot-start.env 2>/dev/null || "
            "echo 'BOT_EDGE_AUTOJS6=0' >> {R}/config/bot-start.env; "
            "grep -q '^BOT_EDGE_ADB_AGENT=' {R}/config/bot-start.env 2>/dev/null || "
            "echo 'BOT_EDGE_ADB_AGENT=0' >> {R}/config/bot-start.env; "
            "grep -q '^BOT_DUAL_PROCESS=' {R}/config/bot-start.env 2>/dev/null || "
            "echo 'BOT_DUAL_PROCESS=1' >> {R}/config/bot-start.env"
        ).format(R=R)
        print(ssh.run(env_patch, 20))

        print("=== stop competing executors ===")
        print(ssh.run(
            f"pkill -f edge_adb_agent.py 2>/dev/null; "
            f"adb -P 5038 -s 127.0.0.1:58433 shell am force-stop org.autojs.autojs6 2>/dev/null; "
            f"adb -P 5039 -s 127.0.0.1:52840 shell am force-stop org.autojs.autojs6 2>/dev/null; "
            f"echo stopped",
            30,
        ))

        print("=== deploy right OSS stack (u2 + adb-clip + ADB Keyboard) ===")
        print(ssh.run(f"bash {R}/scripts/deploy-listener-oss-stack.sh 2>&1 | tail -30", 300))

        print("=== reload dual workers ===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -20", 300))

        print("=== edge_brain health ===")
        print(ssh.run(f"bash {R}/scripts/edge_brain_start.sh 2>&1 | tail -5", 25))
        print(ssh.run("curl -sf http://127.0.0.1:8790/health; echo", 15))

        print("=== process audit ===")
        print(ssh.run(
            "pgrep -af 'bot_dual_supervisor|bot_55chat_daemon|edge_brain' | grep -v pgrep; "
            "pgrep -af edge_adb_agent || echo 'OK: no edge_adb_agent'",
            20,
        ))


def main() -> int:
    local_validate()
    vps_align()
    print("EDGE_ALIGN_OSS_PRODUCTION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
