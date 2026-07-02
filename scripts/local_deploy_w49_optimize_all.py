#!/usr/bin/env python3
"""W49 全局优化真实部署：铁律7(19:35) + 发图验真 + ADB去重 + 隧道验收 + 环境审计。"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"


def _run_local(script: str) -> int:
    print(f"\n{'='*60}\n>>> {script}\n{'='*60}")
    rc = subprocess.call([sys.executable, str(ROOT / "scripts" / script)], cwd=str(ROOT))
    print(f"<<< {script} exit={rc}")
    return rc


def main() -> int:
    report: dict[str, object] = {"job": "w49_optimize_all", "steps": []}
    cfg = load_vps_config(ROOT, prompt_password=False)

    steps = [
        ("iron_law_7", lambda: _run_local("local_deploy_iron_law_7.py")),
        ("settle_verify", lambda: _run_local("local_deploy_settle_verify.py")),
    ]
    for name, fn in steps:
        rc = fn()
        report["steps"].append({"name": name, "ok": rc == 0})
        if rc != 0:
            print(f"[WARN] {name} returned {rc}, continuing")

    with VpsSSH(cfg) as ssh:
        print("\n=== reconnect-dual-adb (dedupe + offline cleanup) ===")
        adb_out = ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 120)
        print(adb_out[-2000:] if len(adb_out) > 2000 else adb_out)
        report["steps"].append({"name": "reconnect_adb", "ok": "OK right" in adb_out and "OK left" in adb_out})

        print("\n=== post-task tunnel verify ===")
        verify_out = ssh.run(f"bash {R}/scripts/vps_post_task_tunnel_verify.sh 2>&1", 90)
        print(verify_out)
        report["steps"].append(
            {
                "name": "tunnel_verify",
                "ok": (
                    ("OK_RIGHT" in verify_out and "OK_LEFT" in verify_out)
                    or "TUNNEL_OK" in verify_out
                ),
            }
        )

        print("\n=== append daily-mem-cycle log ===")
        ssh.run(
            f"cd {R} && {PY} scripts/daily_memory_cycle.py >> {R}/logs/daily-mem-cycle.log 2>&1",
            180,
        )
        mem_log = ssh.run(f"tail -5 {R}/logs/daily-mem-cycle.log 2>/dev/null", 15)
        print(mem_log)
        report["steps"].append({"name": "mem_cycle_log", "ok": '"ok"' in mem_log or "disk_clean" in mem_log})

        cron = ssh.run("crontab -l 2>/dev/null", 10)
        report["cron"] = cron
        report["steps"].append({"name": "cron_1935", "ok": "35 19" in cron and "daily_memory_cycle" in cron})

    print("\n=== global env audit ===")
    audit_rc = _run_local("_w49_global_env_audit.py")
    report["steps"].append({"name": "global_audit", "ok": audit_rc == 0})

    art = ROOT / "artifacts" / "w49-optimize-all.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    fails = [s for s in report["steps"] if not s.get("ok")]
    print(f"\nW49优化部署: {len(report['steps'])-len(fails)}/{len(report['steps'])} PASS → {art}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
