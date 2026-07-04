#!/usr/bin/env python3
"""左机 MediaStore 相册幽灵图一次性清理。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ephemeral_burn import _mediastore_image_count, purge_gallery_bot_images
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"


def main() -> int:
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        for rel in ("bot_ops/ephemeral_burn.py", "bot_55chat_daemon.py"):
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
        ssh.run(f"{PY} -m py_compile {R}/bot_ops/ephemeral_burn.py {R}/bot_55chat_daemon.py", 25)
        print("=== before ===")
        print(ssh.run(
            f"cd {R} && {PY} -c \"from bot_ops.ephemeral_burn import _mediastore_image_count; "
            f"print(_mediastore_image_count('localhost:52840'))\"",
            30,
        ))
        print("=== purge ===")
        print(ssh.run(
            f"cd {R} && {PY} -c \"from bot_ops.ephemeral_burn import purge_gallery_bot_images; "
            f"print(purge_gallery_bot_images('localhost:52840'))\"",
            180,
        ))
        print("=== after ===")
        print(ssh.run(
            f"cd {R} && {PY} -c \"from bot_ops.ephemeral_burn import _mediastore_image_count; "
            f"print(_mediastore_image_count('localhost:52840'))\"",
            30,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
