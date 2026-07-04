#!/usr/bin/env python3
"""结算热路径：capture_ipc + 断点修复 + env + reload 部署。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

SPEED_ENV = [
    "BOT_DUAL_PROCESS=1",
    "BOT_SETTLE_LOOP_SEC=0.25",
    "BOT_DRAW_FETCH_SEC=0.5",
    "BOT_ANNOUNCE_LOOP_SEC=0.25",
    "BOT_SETTLE_SEND_RETRY_SEC=5",
    "BOT_SETTLE_TRADE_FLOW_TIMEOUT=1.5",
    "BOT_IMG_LOCKED=1",
    "BOT_IMG_FAST=1",
    "BOT_IMG_TRUST_CLICK=1",
    "BOT_CLICKER_STAY_IN_CHAT=0",
    "BOT_GALLERY_PUSH_SETTLE_SEC=0.28",
    "BOT_CLICKER_SEND_IMAGES=1",
    "BOT_SEND_QUEUE=1",
]

UPLOAD = [
    "bot_55chat_daemon.py",
    "bot_ops/capture_ipc.py",
    "scripts/_vps_audit_now.py",
]


def _patch_env(ssh: VpsSSH, r: str) -> None:
    for line in SPEED_ENV:
        key = line.split("=", 1)[0]
        ssh.run(
            f"touch {r}/config/bot-start.env; "
            f"grep -q '^{key}=' {r}/config/bot-start.env && "
            f"sed -i 's|^{key}=.*|{line}|' {r}/config/bot-start.env || "
            f"echo '{line}' >> {r}/config/bot-start.env",
            15,
        )


def main() -> int:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_capture_ipc.py", "-q", "--tb=short"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        return r.returncode

    cfg = load_vps_config(ROOT)
    bot_root = cfg.bot_root
    py = f"{bot_root}/.venv/bin/python3"

    with VpsSSH(cfg) as ssh:
        for rel in UPLOAD:
            ssh.sftp_put(str(ROOT / rel), f"{bot_root}/{rel}")
        ssh.run(f"find {bot_root}/scripts -name '*.sh' -exec sed -i 's/\\r$//' {{}} + 2>/dev/null", 30)
        print("=== patch env ===")
        _patch_env(ssh, bot_root)
        steps = [
            (f"{py} -m py_compile {bot_root}/bot_55chat_daemon.py {bot_root}/bot_ops/capture_ipc.py", 25),
            (f"rm -f {bot_root}/data/capture_ipc/pending/*.json; mkdir -p {bot_root}/data/capture_ipc/inflight", 10),
            (f"grep -c inflight {bot_root}/bot_ops/capture_ipc.py", 5),
            (f"grep 'process_round_settlement' {bot_root}/bot_55chat_daemon.py | head -2", 5),
            (f"bash {bot_root}/scripts/reconnect-dual-adb.sh 2>&1 | tail -8", 90),
            (
                f"pkill -HUP -f 'bot_dual_supervisor' 2>/dev/null; sleep 2; "
                f"pkill -9 -f 'spawn_main' 2>/dev/null; sleep 2; "
                f"cd {bot_root} && nohup {py} -u {bot_root}/bot_dual_supervisor.py "
                f">> {bot_root}/logs/dual-supervisor.log 2>&1 & sleep 16; "
                f"pgrep -af 'dual_supervisor|spawn_main' | grep -v pgrep",
                60,
            ),
            (f"grep -E 'capture-ipc|结算时序|预推相册|SETTLE_LOOP' {bot_root}/config/bot-start.env", 10),
            (f"grep -E '结算线程|capture-ipc|DEPLOY LOCK' {bot_root}/logs/dual-supervisor.log | tail -12", 15),
        ]
        for cmd, timeout in steps:
            print(">>>", cmd[:90])
            print(ssh.run(cmd, timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
