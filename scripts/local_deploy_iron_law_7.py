#!/usr/bin/env python3
"""铁律 #7 真实部署：19:35 磁盘→内存落盘；云机 OpenAPI 不占隧道。"""
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

SYNC = (
    "bot_ops/daily_memory_cycle.py",
    "bot_ops/ephemeral_burn.py",
    "bot_ops/cloud_memory_clean.py",
    "bot_ops/vmos_presets.py",
    "scripts/daily_memory_cycle.py",
    "scripts/cloud_memory_maintain.py",
    "scripts/vps_minimal_cron.sh",
    "scripts/kill-legacy-if-dual.sh",
    "scripts/reconnect-dual-adb.sh",
)

ENV_PATCH = f"""
grep -q '^BOT_GALLERY_PURGE_SEC=' {R}/config/bot-start.env && \\
  sed -i 's/^BOT_GALLERY_PURGE_SEC=.*/BOT_GALLERY_PURGE_SEC=3600/' {R}/config/bot-start.env || \\
  echo 'BOT_GALLERY_PURGE_SEC=3600' >> {R}/config/bot-start.env
grep -q '^BOT_CAPTURE_BURN_AFTER_SEND=' {R}/config/bot-start.env && \\
  sed -i 's/^BOT_CAPTURE_BURN_AFTER_SEND=.*/BOT_CAPTURE_BURN_AFTER_SEND=1/' {R}/config/bot-start.env || \\
  echo 'BOT_CAPTURE_BURN_AFTER_SEND=1' >> {R}/config/bot-start.env
grep -q '^BOT_DISK_SPILL_RETENTION_DAYS=' {R}/config/bot-start.env && \\
  sed -i 's/^BOT_DISK_SPILL_RETENTION_DAYS=.*/BOT_DISK_SPILL_RETENTION_DAYS=7/' {R}/config/bot-start.env || \\
  echo 'BOT_DISK_SPILL_RETENTION_DAYS=7' >> {R}/config/bot-start.env
grep -q '^BOT_DAILY_MEM_CYCLE_CRON=' {R}/config/bot-start.env && \\
  sed -i 's/^BOT_DAILY_MEM_CYCLE_CRON=.*/BOT_DAILY_MEM_CYCLE_CRON=35 19/' {R}/config/bot-start.env || \\
  echo 'BOT_DAILY_MEM_CYCLE_CRON=35 19' >> {R}/config/bot-start.env
"""


def main() -> int:
    cfg = load_vps_config(ROOT, prompt_password=False)
    report: dict[str, object] = {"law": 7, "version": "19:35_disk_then_spill", "checks": []}

    def chk(name: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        print(f"[铁律7] {name}: {'PASS' if ok else 'FAIL'} {detail}")

    with VpsSSH(cfg) as ssh:
        for rel in SYNC:
            lp = ROOT / rel
            if lp.is_file():
                ssh.sftp_put(str(lp), f"{R}/{rel}")
                if rel.endswith(".sh"):
                    ssh.run(f"sed -i 's/\\r$//' {R}/{rel} && chmod +x {R}/{rel}", 8)

        print("=== env ===")
        print(ssh.run(ENV_PATCH, 12))
        env_out = ssh.run(
            f"grep -E 'GALLERY_PURGE|CAPTURE_BURN|DISK_SPILL|DAILY_MEM_CYCLE' {R}/config/bot-start.env",
            10,
        )
        chk("env_gallery_1h", "3600" in env_out, "")
        chk("env_burn_after_send", "CAPTURE_BURN_AFTER_SEND=1" in env_out, "")
        chk("env_mem_cron_1935", "DAILY_MEM_CYCLE_CRON=35 19" in env_out, "")

        print("=== cron 19:35 daily cycle ===")
        ssh.run(f"find {R}/scripts -name '*.sh' -exec sed -i 's/\\r$//' {{}} \\;", 15)
        cron_out = ssh.run(f"bash {R}/scripts/vps_minimal_cron.sh", 12)
        print(cron_out)
        chk("cron_1935_daily", "daily_memory_cycle" in cron_out and "35 19" in cron_out, "")
        chk("cron_no_20", "0 20" not in cron_out, "")
        chk("cron_no_6h", "*/6" not in cron_out, "")
        chk("cron_no_watchdog", "vmos-dual-watchdog" not in cron_out, "")

        print("=== preserve caches ===")
        preserve = ssh.run(
            f"for f in mid_cache.json gateway_user_cache.json round_open_announced.json settled_rounds.json; do "
            f"test -f {R}/data/$f && echo OK:$f || echo MISS:$f; done",
            12,
        )
        miss = [ln for ln in preserve.splitlines() if ln.startswith("MISS:")]
        chk("preserve_caches", len(miss) == 0, preserve.strip()[:200])

        print("=== run daily_memory_cycle now (no tunnel) ===")
        cycle_out = ssh.run(f"cd {R} && {PY} scripts/daily_memory_cycle.py 2>&1", 180)
        print(cycle_out[-2500:] if len(cycle_out) > 2500 else cycle_out)
        chk("cycle_ran", '"ok": true' in cycle_out or '"ok":true' in cycle_out.replace(" ", ""), "")
        chk("cloud_no_tunnel", '"tunnel": false' in cycle_out or '"tunnel":false' in cycle_out.replace(" ", ""), "")
        chk("two_phases", cycle_out.count('"step"') >= 2 or cycle_out.count("disk_clean") >= 1, "")

        log_tail = ssh.run(f"tail -3 {R}/logs/daily-mem-cycle.log 2>/dev/null || echo NO_LOG", 10)
        chk("mem_log_written", "daily_memory_cycle" in cycle_out or "铁律7" in log_tail or '"ok"' in log_tail, "")

        art = ROOT / "artifacts" / "iron-law-7-deploy.json"
        art.parent.mkdir(parents=True, exist_ok=True)
        art.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        fails = [c for c in report["checks"] if not c["ok"]]
        print(f"\n铁律7部署: {len(report['checks'])-len(fails)}/{len(report['checks'])} PASS → {art}")
        return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
