#!/usr/bin/env python3
"""左机困附件/相册 → dismiss + 回群 heal（VPS 远程执行）。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH


def main() -> int:
    cfg = load_vps_config(ROOT)
    r = cfg.bot_root
    py = f"{r}/.venv/bin/python3"
    remote = f"""
set -a; source {r}/config/bot-start.env 2>/dev/null; set +a
export BOT_ROOT={r}
cd {r}
{py} - <<'PY'
import os, sys
sys.path.insert(0, {r!r})
os.chdir({r!r})
from bot_ops.runtime import load_bot_runtime
from bot_55chat_daemon import (
    _dismiss_image_picker,
    api,
    recover_clicker_to_group_minimal,
    ui_hierarchy,
    collect_ui_texts,
    clicker_composer_or_gallery_ready,
)

rt = load_bot_runtime()
_out = __import__("subprocess").check_output(["adb", "devices", "-l"], text=True)
serial = next(
    (ln.split()[0] for ln in _out.splitlines() if f":{rt.clicker_adb_port}" in ln and " device" in ln),
    f"localhost:{rt.clicker_adb_port}",
)
bots = api("GET", "/api/bots") or []
bot = next((b for b in bots if str(b.get("id")) == "bot-3"), {{}})
print("serial", serial)
_dismiss_image_picker(serial)
ok = recover_clicker_to_group_minimal(serial, bot)
print("recover", ok, "ready", clicker_composer_or_gallery_ready(serial))
root = ui_hierarchy(serial)
texts = collect_ui_texts(root) if root is not None else []
print("ui_sample", texts[:12])
PY
"""
    with VpsSSH(cfg) as ssh:
        print(ssh.run(remote, 90))
        print("=== tail settle ===")
        print(
            ssh.run(
                f"grep -E 'capture-ipc|批量发图|clicker-img' {r}/logs/dual-supervisor.log | tail -8",
                15,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
