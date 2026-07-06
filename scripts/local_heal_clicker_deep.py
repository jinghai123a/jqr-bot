#!/usr/bin/env python3
"""左机深度 heal：拉起 55M + minimal 回群。"""
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
    api,
    launch_messenger_app,
    recover_clicker_to_group_minimal,
    dismiss_clicker_stuck_surface,
    clicker_composer_or_gallery_ready,
    is_55m_foreground,
    is_on_launcher,
    ui_hierarchy,
    collect_ui_texts,
    wc,
)

rt = load_bot_runtime()
_out = __import__("subprocess").check_output(["adb", "devices", "-l"], text=True)
serial = next(
    (ln.split()[0] for ln in _out.splitlines() if f":{rt.clicker_adb_port}" in ln and " device" in ln),
    f"localhost:{rt.clicker_adb_port}",
)
bot = next((b for b in (api("GET", "/api/bots") or []) if str(b.get("id")) == "bot-3"), {{}})
print("serial", serial, "fg", is_55m_foreground(serial), "launcher", is_on_launcher(serial))
dismiss_clicker_stuck_surface(serial)
if not is_55m_foreground(serial) or is_on_launcher(serial):
    launch_messenger_app(serial)
    wc(1.2, 0.4)
ok = recover_clicker_to_group_minimal(serial, bot)
root = ui_hierarchy(serial)
print("recover", ok, "ready", clicker_composer_or_gallery_ready(serial))
print("ui", collect_ui_texts(root)[:15] if root else [])
PY
pgrep -af spawn_main | head -3
"""
    with VpsSSH(cfg) as ssh:
        print(ssh.run(remote, 120))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
