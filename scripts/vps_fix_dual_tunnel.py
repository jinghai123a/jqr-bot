#!/usr/bin/env python3
"""VPS 双隧道修复：强制 OpenAPI 分 pad 刷新，验 android_id 不同，再 reload。"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
ART = ROOT / "artifacts" / "vps-tunnel-fix.json"


def main() -> int:
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    lport, rport = str(pads["left"]["local_port"]), str(pads["right"]["local_port"])
    report: dict = {"ts": datetime.now(timezone.utc).isoformat(), "steps": []}
    rc = 0

    def step(name: str, ok: bool, detail: str) -> None:
        nonlocal rc
        if not ok:
            rc = 1
        report["steps"].append({"name": name, "ok": ok, "detail": detail[:4000]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n{detail[:1200]}", flush=True)

    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        ssh.run(
            "pkill -f vmos-refresh-tunnels.py 2>/dev/null; sleep 2; "
            f"rm -f {R}/logs/.vmos-refresh.lock; echo cleared",
            20,
        )

        for side in ("right", "left"):
            print(f"=== OpenAPI refresh {side} ===", flush=True)
            log = f"{R}/logs/refresh-{side}.log"
            out = ssh.run_nohup(
                f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --reconnect --side {side}",
                log_path=log,
                max_wait=480.0,
            )
            step(f"refresh_{side}", "Traceback" not in out and ("updated" in out.lower() or "OK" in out or "already" in out.lower() or "wrote" in out.lower()), out[-1500:])

        print("=== reconnect-dual-adb ===", flush=True)
        recon = ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -15", 180)
        adb = ssh.run("adb devices -l", 20)
        step("reconnect", lport in adb and rport in adb, f"{recon}\n{adb}")

        ids = {}
        for p in (lport, rport):
            aid = ssh.run(f"adb -s localhost:{p} shell settings get secure android_id 2>/dev/null", 20).strip()
            model = ssh.run(f"adb -s localhost:{p} shell getprop ro.product.model 2>/dev/null", 20).strip()
            ids[p] = {"android_id": aid, "model": model}
        distinct = ids[lport]["android_id"] and ids[lport]["android_id"] != ids[rport]["android_id"]
        step("distinct_devices", distinct, json.dumps(ids, ensure_ascii=False))

        print("=== reload dual (MANUAL_IN_GROUP) ===", flush=True)
        ssh.run(
            f"grep -q '^BOT_MANUAL_IN_GROUP=' {R}/config/bot-start.env && "
            f"sed -i 's/^BOT_MANUAL_IN_GROUP=.*/BOT_MANUAL_IN_GROUP=1/' {R}/config/bot-start.env || "
            f"echo 'BOT_MANUAL_IN_GROUP=1' >> {R}/config/bot-start.env",
            15,
        )
        reload = ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -12", 300)
        procs = ssh.run("pgrep -af 'bot_dual_supervisor|spawn_main' | grep -v pgrep | head -6", 15)
        step("reload", "spawn_main" in procs or "bot_dual_supervisor" in procs, f"{reload}\n{procs}")

        time.sleep(50)
        verify = ssh.run(
            f"cd {R} && {PY} scripts/verify_group_announce_outgoing.py "
            f"--left 127.0.0.1:{lport} --right 127.0.0.1:{rport} 2>&1",
            180,
        )
        step("verify_out", "verdict=PASS" in verify, verify)

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
