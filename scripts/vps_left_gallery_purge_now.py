#!/usr/bin/env python3
"""左机 DCIM/MediaStore 幽灵图一次性清理 + 计数验收。"""
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


def _purge_script(serial: str) -> str:
    return f"""import os
from bot_ops.ephemeral_burn import (
    _mediastore_image_count,
    _mediastore_image_ids,
    _purge_mediastore_by_ids,
    _adb_shell,
)
s = "{serial}"
b = _mediastore_image_count(s)
print("before", b, flush=True)
for rnd in range(30):
    n = _mediastore_image_count(s)
    if n <= 40:
        print("done", n, flush=True)
        break
    ids = _mediastore_image_ids(s, limit=200)
    d = _purge_mediastore_by_ids(s, ids) if ids else 0
    print("round", rnd, "count", n, "ids", len(ids), "del", d, flush=True)
    if not ids:
        _adb_shell(
            s,
            "shell",
            "content query --uri content://media/external/images/media --projection _id | "
            "grep -oE '_id=[0-9]+' | head -200 | cut -d= -f2 | while read id; do "
            "content delete --uri content://media/external/images/media/$id; done",
            timeout=120,
        )
a = _mediastore_image_count(s)
print("after", a, "purged", max(0, b - a), flush=True)
"""


def main() -> int:
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    port = str(pads["left"]["local_port"])
    serial = f"localhost:{port}"
    purge_path = ROOT / "artifacts" / "_left_gallery_purge_run.py"
    purge_path.parent.mkdir(parents=True, exist_ok=True)
    purge_path.write_text(_purge_script(serial), encoding="utf-8")
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        for rel in ("bot_ops/ephemeral_burn.py", "bot_55chat_daemon.py"):
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
        remote_py = f"{R}/scripts/_left_gallery_purge_run.py"
        ssh.sftp_put(str(purge_path), remote_py)
        print(ssh.run("pkill -15 -f spawn_main 2>/dev/null || true; sleep 2; echo paused", 15))
        print(ssh.run(
            f"set -a; source {R}/config/bot-start.env; set +a; cd {R} && PYTHONPATH={R} {PY} -u {remote_py}",
            900,
        ))
        print(ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"{PY} {R}/scripts/vmos_visual_monitor.py --clicker --once 2>&1 | grep state=",
            60,
        ))
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -4", 240))
        ssh.run(f"rm -f {remote_py}", 10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
