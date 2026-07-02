#!/usr/bin/env python3
"""§0 强制闭环：双隧道前置 → 部署/heal → API 续期后必验通 → 双机回群。"""
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

SYNC = (
    "bot_55chat_daemon.py",
    "bot_ops/adb_isolated.py",
    "bot_ops/process_hygiene.py",
    "bot_tunnel/post_refresh.py",
    "scripts/reconnect-dual-adb.sh",
    "scripts/vps_post_task_tunnel_verify.sh",
    "scripts/vmos-refresh-tunnels.py",
    "scripts/vmos-maintenance-tunnel-cycle.sh",
    "scripts/vps_heal_group_closure.py",
    "scripts/reload-dual-workers.sh",
)

ENV_PATCH = f"""
grep -q '^BOT_LISTENER_ANNOUNCE_TRUST_FALLBACK=' {R}/config/bot-start.env && \\
  sed -i 's/^BOT_LISTENER_ANNOUNCE_TRUST_FALLBACK=.*/BOT_LISTENER_ANNOUNCE_TRUST_FALLBACK=0/' {R}/config/bot-start.env || \\
  echo 'BOT_LISTENER_ANNOUNCE_TRUST_FALLBACK=0' >> {R}/config/bot-start.env
grep -q '^BOT_PHYSICAL_OPEN_SNIPPET_P0=' {R}/config/bot-start.env || \\
  echo 'BOT_PHYSICAL_OPEN_SNIPPET_P0=0' >> {R}/config/bot-start.env
"""


def probe_tunnels(ssh: VpsSSH) -> tuple[bool, str]:
    out = ssh.run(
        f"ss -tlnp | grep -E ':58433|:52840' ; "
        f"adb -P 5038 -s 127.0.0.1:58433 shell echo OK_RIGHT 2>&1 ; "
        f"adb -P 5039 -s 127.0.0.1:52840 shell echo OK_LEFT 2>&1",
        25,
    )
    ok = "OK_RIGHT" in out and "OK_LEFT" in out and "58433" in out and "52840" in out
    return ok, out


def ensure_tunnels(ssh: VpsSSH, report: dict) -> bool:
    ok, out = probe_tunnels(ssh)
    report["steps"].append({"name": "tunnel_precheck", "ok": ok, "detail": out[-400:]})
    if ok:
        print("[§0] 双隧道 precheck PASS")
        return True

    print("[§0] 双隧道 offline → reconnect-dual-adb")
    rc_out = ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 120)
    ok, out = probe_tunnels(ssh)
    report["steps"].append({"name": "tunnel_after_reconnect", "ok": ok})
    if ok:
        return True

    print("[§0] reconnect 失败 → OpenAPI 双端续期")
    refresh_out = ssh.run(
        f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --reconnect 2>&1",
        300,
    )
    report["steps"].append({"name": "api_refresh", "ok": "ok" in refresh_out.lower() or "expire" in refresh_out.lower()})
    print(refresh_out[-1500:] if len(refresh_out) > 1500 else refresh_out)

    ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 120)
    verify_out = ssh.run(f"bash {R}/scripts/vps_post_task_tunnel_verify.sh 2>&1", 90)
    ok = "TUNNEL_OK" in verify_out
    report["steps"].append({"name": "tunnel_after_api", "ok": ok, "detail": verify_out[-500:]})
    print(verify_out)
    return ok


def main() -> int:
    report: dict = {"job": "s0_tunnel_heal", "steps": []}
    cfg = load_vps_config(ROOT, prompt_password=False)

    print("=== pytest ===")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "tests/test_bot_tunnel.py", "tests/test_bot_ops.py", "-q"],
        cwd=str(ROOT),
    )
    if rc != 0:
        print("pytest FAIL, abort")
        return rc

    with VpsSSH(cfg) as ssh:
        if not ensure_tunnels(ssh, report):
            print("[§0] ABORT: 双隧道未畅通，停止部署")
            _write_report(report)
            return 1

        for rel in SYNC:
            lp = ROOT / rel
            if lp.is_file():
                ssh.sftp_put(str(lp), f"{R}/{rel}")
                if rel.endswith(".sh"):
                    ssh.run(f"sed -i 's/\\r$//' {R}/{rel} && chmod +x {R}/{rel}", 8)
        print("=== env patch (trust-fallback OFF) ===")
        print(ssh.run(ENV_PATCH, 12))

        print("=== py_compile ===")
        print(ssh.run(f"{PY} -m py_compile {R}/bot_55chat_daemon.py", 30))

        print("=== heal 双机回群 (不 reconnect) ===")
        heal_out = ssh.run(f"cd {R} && {PY} scripts/vps_heal_group_closure.py 2>&1", 180)
        print(heal_out[-2000:] if len(heal_out) > 2000 else heal_out)
        heal_ok = "target_group" in heal_out and "IN_TARGET" in heal_out
        report["steps"].append({"name": "heal_both_in_group", "ok": heal_ok})

        print("=== reload dual workers (keep tunnels) ===")
        print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1", 180))
        time.sleep(12)
        spawn = ssh.run("pgrep -af 'spawn_main|bot_dual_supervisor' | grep -v pgrep | head -4", 12)
        print(spawn)
        report["steps"].append({"name": "spawn_x2", "ok": spawn.count("spawn_main") >= 2})

        print("=== §0 收尾验通 (强制) ===")
        final = ssh.run(f"bash {R}/scripts/vps_post_task_tunnel_verify.sh 2>&1", 90)
        print(final)
        tunnel_ok = "TUNNEL_OK" in final
        report["steps"].append({"name": "tunnel_final_verify", "ok": tunnel_ok})

        print("=== vmos status ===")
        status = ssh.run(f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --status 2>&1", 60)
        print(status)
        report["vmos_status"] = status

        focus = ssh.run(
            "adb -P 5038 -s 127.0.0.1:58433 shell dumpsys window | grep mCurrentFocus; "
            "adb -P 5039 -s 127.0.0.1:52840 shell dumpsys window | grep mCurrentFocus",
            20,
        )
        print("=== focus ===")
        print(focus)
        report["steps"].append(
            {
                "name": "both_group_chat",
                "ok": focus.count("GroupChatActivity") >= 2,
            }
        )

    _write_report(report)
    fails = [s for s in report["steps"] if not s.get("ok")]
    print(f"\n§0闭环: {len(report['steps'])-len(fails)}/{len(report['steps'])} PASS")
    return 1 if fails else 0


def _write_report(report: dict) -> None:
    art = ROOT / "artifacts" / "s0-tunnel-heal.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {art}")


if __name__ == "__main__":
    raise SystemExit(main())
