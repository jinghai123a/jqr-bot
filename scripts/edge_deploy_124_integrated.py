#!/usr/bin/env python3
"""124 架构整合部署：左 JS + edge_brain WS；清旧执行器；减隧道拥堵。"""
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
UPLOAD = [
    "bot_55chat_daemon.py",
    "config/vmos-pads.json",
    "config/55m-knowledge/executor-matrix.json",
    "config/pinned-coords.json",
    "edge_android/settle-left/settle_left.js",
    "edge_android/settle-left/edge_config.json",
    "scripts/edge_auto_bootstrap.sh",
    "scripts/sync_edge_android_coords.py",
]

# 124 模式 env（左机云内 HTTP+tap，右机 ADB 仅发字）
ENV_124 = {
    "BOT_EDGE_MODE": "124",
    "BOT_EDGE_LEFT_JS": "1",
    "BOT_EDGE_AUTOJS6": "1",
    "BOT_EDGE_ADB_AGENT": "0",
    "BOT_CLICKER_SEND_IMAGES": "0",
    "BOT_CLICKER_SETTLE": "0",
    "BOT_ANNOUNCE_LOCKED": "1",
    "BOT_OPEN_FALLBACK_SEC": "0",
    "BOT_LISTENER_FORCE_SCAN_SEC": "3.0",
    "BOT_UI_CACHE_MS": "200",
    "BOT_EDGE_BRAIN_URL": "http://127.0.0.1:8790",
}


def _pytest() -> None:
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_edge_brain.py", "tests/test_announce_locked.py", "-q"],
        cwd=str(ROOT),
    )


def _purge_vps(ssh: VpsSSH) -> None:
    print("=== purge legacy executors ===")
    timers = (
        "vmos-dual-watchdog.timer",
        "vmos-adb-watchdog.timer",
        "vmos-adb-keepalive.timer",
    )
    stop_disable = "; ".join(
        f"systemctl stop {t} 2>/dev/null; systemctl disable {t} 2>/dev/null; systemctl mask {t} 2>/dev/null"
        for t in timers
    )
    print(ssh.run(
        "pkill -f edge_adb_agent.py 2>/dev/null; "
        + stop_disable
        + "; "
        "crontab -l 2>/dev/null | grep -v vmos-dual-watchdog | grep -v cloud_dual_watch | crontab - 2>/dev/null; "
        "echo purge_ok",
        30,
    ))


def _patch_env(ssh: VpsSSH) -> None:
    lines = []
    for k, v in ENV_124.items():
        lines.append(
            f"grep -q '^{k}=' {R}/config/bot-start.env 2>/dev/null && "
            f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || "
            f"echo '{k}={v}' >> {R}/config/bot-start.env"
        )
    print(ssh.run("; ".join(lines), 25))


def _deploy(ssh: VpsSSH) -> None:
    ssh.run(f"mkdir -p {R}/config/55m-knowledge {R}/edge_android/settle-left", 15)
    for rel in UPLOAD:
        local = ROOT / rel
        if local.is_file():
            ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
    ssh.run(
        f"sed -i 's/\\r$//' {R}/scripts/edge_auto_bootstrap.sh && chmod +x {R}/scripts/edge_auto_bootstrap.sh",
        15,
    )
    print(ssh.run(f"cd {R} && .venv/bin/python3 scripts/sync_edge_android_coords.py 2>&1", 30))
    print(ssh.run(f"{R}/.venv/bin/python3 -m py_compile {R}/bot_55chat_daemon.py", 60))


def _stack(ssh: VpsSSH) -> None:
    print(ssh.run(f"bash {R}/scripts/edge_brain_start.sh 2>&1 | tail -3", 20))
    print(ssh.run(f"bash {R}/scripts/deploy-listener-oss-stack.sh 2>&1 | tail -8", 180))
    print(ssh.run(f"bash {R}/scripts/edge_auto_bootstrap.sh 2>&1 | tail -15", 300))
    print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -12", 300))


def _verify(ssh: VpsSSH) -> None:
    print("=== verify ===")
    print(ssh.run(
        "pgrep -af 'edge_brain|bot_dual_supervisor|edge_adb_agent' | grep -v pgrep; "
        "pgrep -af edge_adb_agent || echo OK_no_agent",
        20,
    ))
    print(ssh.run(
        "adb -P 5038 -s 127.0.0.1:58433 shell getprop ro.product.model; "
        "adb -P 5039 -s 127.0.0.1:52840 shell getprop ro.product.model",
        20,
    ))
    print(ssh.run(
        f"grep -E 'BOT_EDGE|BOT_CLICKER_SEND|BOT_EDGE_LEFT' {R}/config/bot-start.env | head -12",
        15,
    ))


def main() -> int:
    _pytest()
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        _purge_vps(ssh)
        _patch_env(ssh)
        _deploy(ssh)
        _stack(ssh)
        _verify(ssh)
    out = ROOT / "artifacts" / "edge-124-deploy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"mode": "124", "env": ENV_124}, indent=2), encoding="utf-8")
    print("EDGE_124_DEPLOY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
