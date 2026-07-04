#!/usr/bin/env python3
"""VPS 侧自愈：重连隧道 + 回群 + 视觉（不调用 VMOS API）。"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).resolve().parent
R = "/home/bot/55chat-bot"
ART = ROOT / "artifacts" / "edge-vps-heal.json"
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402


def main() -> int:
    report: dict = {"ts_utc": datetime.now(timezone.utc).isoformat(), "steps": []}
    rc = 0
    config = load_vps_config(ROOT)

    def step(name: str, ok: bool, detail: str) -> None:
        nonlocal rc
        if not ok:
            rc = 1
        report["steps"].append({"name": name, "ok": ok, "detail": detail[:3000]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail[:800]}", flush=True)

    with VpsSSH(config) as ssh:
        ssh.sftp_put(str(ROOT / "bot_55chat_daemon.py"), f"{R}/bot_55chat_daemon.py")
        ssh.sftp_put(str(ROOT / "bot_ops" / "nav_guard.py"), f"{R}/bot_ops/nav_guard.py")
        for name in ("recover_listener_now.py", "vmos_visual_monitor.py"):
            local = BASE / name
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/scripts/{name}")

        out = ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 150)
        adb = ssh.run("adb devices -l", 30)
        lp, rp = config.clicker_adb_port, config.listener_adb_port
        step("reconnect", lp in adb and rp in adb, f"{out}\n{adb}")

        left_model = ssh.run(f"adb -s 127.0.0.1:{lp} shell getprop ro.product.model 2>/dev/null", 20).strip()
        right_model = ssh.run(f"adb -s 127.0.0.1:{rp} shell getprop ro.product.model 2>/dev/null", 20).strip()
        step("models", True, f"left={left_model!r} right={right_model!r}")

        restart = ssh.run(
            f"sh -c 'pkill -f spawn_main 2>/dev/null; pkill -f bot_dual_supervisor 2>/dev/null; "
            f"rm -f {R}/data/bot.lock.*; sleep 2; "
            f"cd {R} && nohup {R}/.venv/bin/python3 -u {R}/bot_dual_supervisor.py "
            f">> {R}/logs/dual-supervisor.log 2>&1 </dev/null &'",
            30,
        )
        import time

        time.sleep(12)
        daemon = ssh.run("pgrep -af 'bot_dual_supervisor.py|spawn_main' 2>/dev/null | head -8", 20)
        step("restart_daemon", "spawn_main" in daemon or "bot_dual_supervisor" in daemon, f"{restart}\n{daemon}")

        recover = ssh.run(f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 180)
        step("recover", "in_group=True" in recover or "page=target_group" in recover, recover)

        visual = ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"python3 {R}/scripts/vmos_visual_monitor.py --both --once --capture 2>&1",
            120,
        )
        step("visual", "state=target_group" in visual, visual)

    r = subprocess.run([sys.executable, str(BASE / "verify_dual_brain.py")], cwd=ROOT, timeout=180)
    step("verify_dual_brain", r.returncode == 0, f"exit={r.returncode}")

    report["rc"] = rc
    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {ART}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
