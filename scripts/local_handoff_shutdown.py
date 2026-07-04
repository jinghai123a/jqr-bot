#!/usr/bin/env python3
"""关机前 VPS 快照 + 本机关机倒计时。"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402

R = "/home/bot/55chat-bot"
ART = ROOT / "artifacts" / "handoff-shutdown.json"
SHUTDOWN_SEC = 90


def main() -> int:
    snap: dict = {"ts": datetime.now(timezone.utc).isoformat(), "vps": {}, "shutdown_sec": SHUTDOWN_SEC}
    try:
        with VpsSSH(load_vps_config(ROOT)) as ssh:
            snap["vps"]["health"] = ssh.run("curl -sf http://127.0.0.1:8790/health 2>/dev/null || echo DOWN", 15).strip()
            snap["vps"]["procs"] = ssh.run(
                "pgrep -af edge_brain; pgrep -af bot_dual_supervisor; pgrep -af spawn_main | head -3",
                20,
            ).strip()
            snap["vps"]["adb"] = ssh.run("adb devices -l 2>/dev/null | grep -E '52840|58433' || echo none", 15).strip()
            snap["vps"]["cron"] = ssh.run("crontab -l 2>/dev/null | grep -E 'lean-boot|vmos-maintenance|daily_memory' | head -4", 15).strip()
    except Exception as ex:
        snap["vps"]["error"] = str(ex)

    subprocess.run(
        [
            "powershell", "-NoProfile", "-Command",
            "Get-Process python -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -like '*全自动化*' -or $_.CommandLine -match 'local_auto|tunnel_keepalive|edge_mock' } | "
            "Stop-Process -Force -ErrorAction SilentlyContinue",
        ],
        capture_output=True,
        timeout=20,
    )

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")

    msg = "W49 休息：VPS+云机自运行，本机90秒后关机。取消: shutdown /a"
    r = subprocess.run(["shutdown", "/s", "/t", str(SHUTDOWN_SEC), "/c", msg], capture_output=True, text=True)
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    print(f"SHUTDOWN /s /t {SHUTDOWN_SEC} — cancel: shutdown /a")
    print(f"snapshot -> {ART}")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
