#!/usr/bin/env python3
"""诊断左机 MediaStore 清理失败原因。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"


def main() -> int:
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    port = str(pads["left"]["local_port"])
    serial = f"localhost:{port}"
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        ssh.sftp_put(str(ROOT / "bot_ops/ephemeral_burn.py"), f"{R}/bot_ops/ephemeral_burn.py")
        for cmd in (
            f"set -a; source {R}/config/bot-start.env; set +a; adb -P $BOT_CLICKER_ADB_SERVER_PORT devices -l | grep {port}",
            f"set -a; source {R}/config/bot-start.env; set +a; adb -P $BOT_CLICKER_ADB_SERVER_PORT -s {serial} shell ls /sdcard/DCIM/Camera 2>/dev/null | wc -l",
            f"set -a; source {R}/config/bot-start.env; set +a; adb -P $BOT_CLICKER_ADB_SERVER_PORT -s {serial} shell \"content query --uri content://media/external/images/media --projection _id --sort '_id ASC'\" 2>&1 | head -5",
            f"set -a; source {R}/config/bot-start.env; set +a; cd {R} && {PY} -c \""
            f"from bot_ops.ephemeral_burn import _mediastore_image_ids,_purge_mediastore_by_ids,_mediastore_image_count; "
            f"s='{serial}'; ids=_mediastore_image_ids(s,limit=3); print('ids',ids); "
            f"print('del',_purge_mediastore_by_ids(s,ids) if ids else 0); "
            f"print('after',_mediastore_image_count(s))\"",
        ):
            print("===", cmd[:80], "...")
            print(ssh.run(cmd, 120))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
