#!/usr/bin/env python3
"""Deploy expire-aware tunnel refresh + apply W49 manual creds + cron."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
SYNC = [
    "bot_tunnel/expire_schedule.py",
    "bot_tunnel/env_io.py",
    "bot_tunnel/refresh.py",
    "bot_tunnel/__init__.py",
    "scripts/vmos-refresh-tunnels.py",
    "scripts/apply_dual_tunnel_manual.py",
    "scripts/vps_minimal_cron.sh",
    "config/bot-start.env.example",
]


def _load_local_creds() -> None:
    path = ROOT / "config" / "tunnel-creds.local.env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    _load_local_creds()
    cfg = load_vps_config(ROOT, prompt_password=False)
    with VpsSSH(cfg) as ssh:
        for rel in SYNC:
            ssh.sftp_put(str(ROOT / rel), f"{R}/{rel}")
            print("synced", rel)

        print("=== patch bot-start.env expire settings ===")
        patch = f"""
grep -q '^BOT_VMOS_ADB_EXPIRE_MINUTES=' {R}/config/bot-start.env 2>/dev/null && \\
  sed -i 's/^BOT_VMOS_ADB_EXPIRE_MINUTES=.*/BOT_VMOS_ADB_EXPIRE_MINUTES=1440/' {R}/config/bot-start.env || \\
  echo 'BOT_VMOS_ADB_EXPIRE_MINUTES=1440' >> {R}/config/bot-start.env
grep -q '^BOT_VMOS_REFRESH_BUFFER_MINUTES=' {R}/config/bot-start.env 2>/dev/null && \\
  sed -i 's/^BOT_VMOS_REFRESH_BUFFER_MINUTES=.*/BOT_VMOS_REFRESH_BUFFER_MINUTES=120/' {R}/config/bot-start.env || \\
  echo 'BOT_VMOS_REFRESH_BUFFER_MINUTES=120' >> {R}/config/bot-start.env
grep -E 'BOT_VMOS_ADB_EXPIRE|BOT_VMOS_REFRESH_BUFFER' {R}/config/bot-start.env
"""
        print(ssh.run(patch, 20))

        print("=== install cron (hourly expire-if-needed + optional fallback 19:00) ===")
        print(ssh.run(f"bash {R}/scripts/vps_minimal_cron.sh 2>&1", 30))

    # apply manual creds from env (caller must set RIGHT_* / LEFT_*)
    if os.environ.get("RIGHT_SSH_COMMAND") and os.environ.get("LEFT_SSH_COMMAND"):
        print("=== apply dual tunnel manual ===")
        os.environ.setdefault("BOT_VMOS_ADB_EXPIRE_MINUTES", "1440")
        from scripts.apply_dual_tunnel_manual import main as apply_main

        return apply_main()
    print("skip manual creds (set RIGHT_SSH_COMMAND / LEFT_SSH_COMMAND to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
