#!/usr/bin/env python3
"""恢复左机隧道 + 部署 + 相册核清理 + supervisor 重启。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
SERIAL = "localhost:52840"


def deploy(ssh: VpsSSH) -> None:
    for rel in (
        "bot_55chat_daemon.py",
        "bot_ops/ephemeral_burn.py",
        "bot_ops/capture_ipc.py",
    ):
        ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
    print(ssh.run(f"{PY} -m py_compile {R}/bot_55chat_daemon.py {R}/bot_ops/ephemeral_burn.py", 30))


def reconnect_left(ssh: VpsSSH) -> bool:
    print("=== reconnect left tunnel ===")
    ssh.run(f"sh -c 'bash {R}/scripts/tunnel-left.sh >> {R}/logs/tunnel-left.log 2>&1 </dev/null &'", 15)
    for i in range(18):
        time.sleep(5)
        out = ssh.run("adb devices 2>/dev/null", 12)
        print(f"[{i+1}] {out.strip()}")
        if f"{SERIAL}\tdevice" in out or "52840\tdevice" in out:
            return True
    return False


def mediastore_purge(ssh: VpsSSH) -> None:
    print("=== mediastore purge ===")
    code = (
        "from bot_ops.ephemeral_burn import _mediastore_image_count, purge_gallery_bot_images; "
        f"s='{SERIAL}'; "
        "print('before', _mediastore_image_count(s)); "
        "print('purged', purge_gallery_bot_images(s)); "
        "print('after', _mediastore_image_count(s))"
    )
    print(ssh.run(f"cd {R} && {PY} -c \"{code}\"", 300))


def restart_supervisor(ssh: VpsSSH) -> None:
    print("=== restart supervisor ===")
    for pat in ("spawn_main", "bot_dual_supervisor.py"):
        out = ssh.run(f"pgrep -f '{pat}' 2>/dev/null || true", 12).strip()
        for pid in out.split():
            if pid.isdigit():
                ssh.run(f"kill -9 {pid} 2>/dev/null || true", 8)
    time.sleep(2)
    ssh.run(f"rm -f {R}/data/bot.lock.clicker {R}/data/bot.lock.listener", 10)
    ssh.run(
        f"sh -c 'cd {R} && nohup {PY} -u {R}/bot_dual_supervisor.py "
        f">> {R}/logs/dual-supervisor.log 2>&1 </dev/null &'",
        15,
    )
    time.sleep(12)
    print(ssh.run("pgrep -af 'bot_dual_supervisor.py|spawn_main' 2>/dev/null | head -6", 15))
    print(ssh.run(f"tail -8 {R}/logs/dual-supervisor.log", 15))


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        deploy(ssh)
        if not reconnect_left(ssh):
            print("WARN: left tunnel still offline after reconnect attempts")
        else:
            mediastore_purge(ssh)
        restart_supervisor(ssh)
        print("=== final adb ===")
        print(ssh.run("adb devices", 15))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
