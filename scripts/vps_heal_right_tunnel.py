#!/usr/bin/env python3
"""VPS 右隧道自愈：清锁 → OpenAPI 续凭证 → 重连（避开 IP ban 旧密码风暴）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        print("=== clear stale lock ===")
        print(ssh.run(f"pkill -f 'vmos-refresh-tunnels.py' 2>/dev/null; sleep 1; rm -f {R}/data/vmos-refresh.lock; echo ok", 20))

        print("=== OpenAPI refresh right only ===")
        out = ssh.run(
            f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --reconnect --side right 2>&1",
            300,
        )
        print(out[-4000:])

        print("=== tunnel-right retry ===")
        print(ssh.run(f"bash {R}/scripts/tunnel-right.sh 2>&1 | tail -15", 120))

        print("=== adb devices ===")
        adb = ssh.run("adb devices -l", 20)
        print(adb)

        ok = "58433" in adb and "device" in adb
        if ok:
            print(ssh.run(
                f"adb -s 127.0.0.1:58433 shell getprop ro.product.model; "
                f"adb -s 127.0.0.1:58433 shell echo probe_ok",
                25,
            ))
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
