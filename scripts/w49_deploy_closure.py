#!/usr/bin/env python3
"""W49 闭环部署 Phase0-2：停干扰 + 代码上线 + 左隧道刷新（不自动回群）。"""
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
UPLOAD = (
    "bot_55chat_daemon.py",
    "bot_ops/nav_guard.py",
    "config/vmos-pads.json",
    "scripts/edge_deploy_124_integrated.py",
)


def _pytest() -> None:
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_nav_guard.py", "tests/test_announce_locked.py", "-q"],
        cwd=str(ROOT),
    )


def _mask_timers(ssh: VpsSSH) -> None:
    timers = (
        "vmos-dual-watchdog.timer",
        "vmos-adb-watchdog.timer",
        "vmos-adb-keepalive.timer",
    )
    cmd = "pkill -f edge_adb_agent.py 2>/dev/null; "
    for t in timers:
        cmd += (
            f"sudo systemctl stop {t} 2>/dev/null; "
            f"sudo systemctl disable {t} 2>/dev/null; "
        )
    cmd += f"systemctl is-enabled {' '.join(timers)} 2>&1; echo timers_done"
    print("=== mask timers ===")
    print(ssh.run(cmd, 30))
    print(ssh.run(f"systemctl is-enabled {' '.join(timers)} 2>&1", 10))


def _upload(ssh: VpsSSH) -> None:
    for rel in UPLOAD:
        local = ROOT / rel
        if local.is_file():
            ssh.sftp_put(str(local), f"{R}/{rel}")
    print(ssh.run(f"{R}/.venv/bin/python3 -m py_compile {R}/bot_55chat_daemon.py", 45))


def _reload(ssh: VpsSSH) -> None:
    print("=== reload workers ===")
    print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -12", 300))


def _left_tunnel(ssh: VpsSSH) -> None:
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    port = str(pads["left"]["local_port"])
    print("=== left tunnel reconnect (no recover) ===")
    print(ssh.run(f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -8", 120))
    print(ssh.run(f"adb connect localhost:{port} 2>&1; adb devices -l", 25))
    print(ssh.run(f"adb -s localhost:{port} shell getprop ro.product.model", 15))
    model = ssh.run(f"adb -s localhost:{port} shell getprop ro.product.model", 15).strip()
    expect = str(pads["left"].get("expect_model") or "Pixel XL")
    if expect.lower() not in model.lower():
        print(f"BLOCKED: left model={model!r} expect {expect!r} — VMOS API refresh or console manual tunnel required")


def _verify(ssh: VpsSSH) -> None:
    print("=== visual ===")
    print(ssh.run(
        f"cd {R} && W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
        f".venv/bin/python3 scripts/vmos_visual_monitor.py --both --once 2>&1",
        90,
    ))
    print("=== env ===")
    print(ssh.run(
        f"grep -E 'MANUAL_IN_GROUP|EDGE_MODE|CLICKER_SEND' {R}/config/bot-start.env",
        10,
    ))


def main() -> int:
    _pytest()
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        _mask_timers(ssh)
        _upload(ssh)
        _reload(ssh)
        _left_tunnel(ssh)
        _verify(ssh)
    print("W49_DEPLOY_CLOSURE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
