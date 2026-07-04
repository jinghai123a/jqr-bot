#!/usr/bin/env python3
"""VPS 生产部署 + 实测验收（docs/用户使用.md）— 不刷新 OpenAPI、不关机。"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
ART = ROOT / "artifacts" / "production-deploy-run.json"

UPLOAD = (
    "bot_55chat_daemon.py",
    "bot_dual_supervisor.py",
    "bot_ops/nav_guard.py",
    "bot_ops/announce_audit.py",
    "bot_ops/config.py",
    "bot_ops/ssh_client.py",
    "config/vmos-pads.json",
    "config/pinned-coords.json",
    "scripts/tunnel-connect-official.sh",
    "scripts/tunnel-left.sh",
    "scripts/tunnel-right.sh",
    "scripts/reconnect-dual-adb.sh",
    "scripts/verify_group_announce_outgoing.py",
    "scripts/vmos_visual_monitor.py",
    "scripts/patch_speed_env.py",
    "scripts/edge_brain_start.sh",
)

ENV_KV = (
    "BOT_MANUAL_IN_GROUP=1",
    "BOT_EDGE_ADB_AGENT=0",
    "BOT_EDGE_AUTOJS6=0",
    "BOT_DUAL_PROCESS=1",
    "BOT_CLICKER_SEND_IMAGES=1",
    "BOT_CLICKER_SETTLE=1",
    "BOT_LISTENER_ZERO_NAV=1",
    "BOT_LISTENER_ADB_PORT=58433",
    "BOT_CLICKER_ADB_PORT=52840",
    "BOT_SRE_HEAL_COOLDOWN_SEC=300",
    "BOT_ANNOUNCE_LOCKED=1",
    "EDGE_BRAIN_JWT_SECRET=w49-edge-aps-jwt-secret",
)


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
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if detail.strip():
            print(detail[:2000])

    try:
        subprocess.check_call(
            [sys.executable, "-m", "pytest", "tests/test_nav_guard.py", "tests/test_announce_locked.py", "-q", "--tb=line"],
            cwd=str(ROOT),
        )
        subprocess.check_call([sys.executable, "-m", "py_compile", str(ROOT / "bot_55chat_daemon.py")], cwd=str(ROOT))
        step("local_tests", True, "pytest+compile OK")
    except subprocess.CalledProcessError as ex:
        step("local_tests", False, str(ex))
        return 1

    with VpsSSH(load_vps_config(ROOT)) as ssh:
        print("=== stop interference ===")
        ssh.run(
            "pkill -9 -f vmos-refresh-tunnels.py 2>/dev/null; "
            "pkill -f edge_adb_agent.py 2>/dev/null; "
            f"rm -f {R}/logs/.vmos-refresh.lock; echo stopped",
            20,
        )

        uploaded = []
        for rel in UPLOAD:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
                uploaded.append(rel)
        step("upload", True, "\n".join(uploaded))

        ssh.run(
            "for s in reconnect-dual-adb.sh tunnel-left.sh tunnel-right.sh tunnel-connect-official.sh "
            "reload-dual-workers.sh edge_brain_start.sh; do "
            f"sed -i 's/\\r$//' {R}/scripts/$s 2>/dev/null; chmod +x {R}/scripts/$s 2>/dev/null; done; echo ok",
            20,
        )

        for kv in ENV_KV:
            k, v = kv.split("=", 1)
            ssh.run(
                f"grep -q '^{k}=' {R}/config/bot-start.env && "
                f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || "
                f"echo '{k}={v}' >> {R}/config/bot-start.env",
                12,
            )
        ssh.run(f"{PY} {R}/scripts/patch_speed_env.py 2>&1 | tail -5", 30)
        step("env", True, ssh.run(f"grep -E 'MANUAL_IN_GROUP|CLICKER_SEND|EDGE_ADB|LISTENER_ADB|CLICKER_ADB' {R}/config/bot-start.env", 15))

        recon = ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 180)
        adb = ssh.run("adb devices -l", 20)
        ok_adb = lport in adb and rport in adb
        step("tunnels", ok_adb, f"{recon[-1500:]}\n{adb}")

        if not ok_adb:
            for script in ("tunnel-right.sh", "tunnel-left.sh"):
                ssh.run(f"bash {R}/scripts/{script} 2>&1", 90)
            adb = ssh.run("adb devices -l", 20)
            ok_adb = lport in adb and rport in adb
            step("tunnels_retry", ok_adb, adb)

        ssh.run(f"bash {R}/scripts/edge_brain_start.sh 2>&1 | tail -3", 25)
        time.sleep(3)
        health = ssh.run("curl -sf http://127.0.0.1:8790/health; echo", 10)
        step("edge_brain", '"ok"' in health, health)

        reload = ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -15", 300)
        time.sleep(12)
        procs = ssh.run("pgrep -af 'edge_brain|bot_dual_supervisor|spawn_main' | grep -v pgrep", 20)
        step("supervisor", "spawn_main" in procs and "bot_dual_supervisor" in procs, f"{reload}\n{procs}")

        visual = ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"{PY} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1",
            120,
        )
        in_grp = visual.count("state=target_group") >= 2
        step("visual", in_grp, visual)

        verify = ssh.run(
            f"cd {R} && {PY} scripts/verify_group_announce_outgoing.py "
            f"--left localhost:{lport} --right localhost:{rport} 2>&1",
            180,
        )
        step("verify_out", "verdict=PASS" in verify, verify)

        logs = ssh.run(
            f"tail -20 {R}/logs/dual-supervisor.log 2>/dev/null; echo '---'; "
            f"grep -E 'ERROR|Traceback|LISTENER 未连接' {R}/logs/dual-supervisor.log 2>/dev/null | tail -5 || echo no_errors",
            20,
        )
        has_fatal = "Traceback" in logs and "LISTENER 未连接" in logs
        step("logs_clean", not has_fatal, logs[-1500:])

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {ART}")
    print(f"DEPLOY_RC={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
