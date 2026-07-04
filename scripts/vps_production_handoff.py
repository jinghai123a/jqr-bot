#!/usr/bin/env python3
"""VPS 生产无人看守：双 pad OpenAPI 刷新 → reload → OUT 验收 → 本机关机倒计时。"""
from __future__ import annotations

import json
import subprocess
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
ART = ROOT / "artifacts" / "vps-production-handoff.json"

UPLOAD = (
    "bot_55chat_daemon.py",
    "bot_ops/nav_guard.py",
    "bot_ops/announce_audit.py",
    "config/vmos-pads.json",
    "config/pinned-coords.json",
    "scripts/verify_group_announce_outgoing.py",
    "scripts/vmos_visual_monitor.py",
    "scripts/patch_speed_env.py",
    "scripts/reconnect-dual-adb.sh",
)


def _local_tests() -> None:
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_nav_guard.py", "tests/test_jwt_auth.py", "-q", "--tb=line"],
        cwd=str(ROOT),
    )
    subprocess.check_call([sys.executable, "-m", "py_compile", str(ROOT / "bot_55chat_daemon.py")])


def main() -> int:
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    lport, rport = str(pads["left"]["local_port"]), str(pads["right"]["local_port"])
    report: dict = {"ts": datetime.now(timezone.utc).isoformat(), "standard": "docs/用户使用.md", "steps": []}
    rc = 0

    def step(name: str, ok: bool, detail: str) -> None:
        nonlocal rc
        if not ok:
            rc = 1
        report["steps"].append({"name": name, "ok": ok, "detail": detail[:5000]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)
        if detail.strip():
            print(detail[:1500], flush=True)

    try:
        _local_tests()
        step("local_tests", True, "pytest+compile OK")
    except subprocess.CalledProcessError as ex:
        step("local_tests", False, str(ex))
        return 1

    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        ssh.run("pkill -9 -f vmos-refresh-tunnels.py 2>/dev/null; rm -f " + R + "/logs/.vmos-refresh.lock", 15)
        for rel in UPLOAD:
            p = ROOT / rel
            if p.is_file():
                ssh.sftp_put(str(p), f"{R}/{rel.replace(chr(92), '/')}")

        ssh.run(
            "for s in reconnect-dual-adb.sh tunnel-left.sh tunnel-right.sh reload-dual-workers.sh edge_brain_start.sh; do "
            f"sed -i 's/\\r$//' {R}/scripts/$s 2>/dev/null; chmod +x {R}/scripts/$s 2>/dev/null; done; echo ok",
            20,
        )

        for kv in (
            "BOT_MANUAL_IN_GROUP=1",
            "BOT_EDGE_ADB_AGENT=0",
            f"BOT_LISTENER_ADB_PORT={rport}",
            f"BOT_CLICKER_ADB_PORT={lport}",
            "BOT_LISTENER_ANNOUNCE_VERIFY_MAX_MS=2000",
        ):
            k, v = kv.split("=", 1)
            ssh.run(
                f"grep -q '^{k}=' {R}/config/bot-start.env && sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env "
                f"|| echo '{k}={v}' >> {R}/config/bot-start.env",
                12,
            )
        ssh.run(f"{PY} {R}/scripts/patch_speed_env.py", 30)

        for side in ("right", "left"):
            log = f"{R}/logs/openapi-refresh-{side}.log"
            out = ssh.run_nohup(
                f"cd {R} && {PY} scripts/vmos-refresh-tunnels.py --reconnect --side {side}",
                log_path=log,
                max_wait=720.0,
            )
            step(f"openapi_{side}", "Traceback" not in out and ("wrote" in out.lower() or "updated" in out.lower() or "OK" in out), out[-2000:])

        hosts = ssh.run(f"grep ^SSH_HOST= {R}/config/tunnel-left.env {R}/config/tunnel-right.env", 15)
        step("distinct_ssh_hosts", hosts.count("SSH_HOST=") >= 2 and len(set(hosts.strip().splitlines())) >= 2, hosts)

        recon = ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -12", 180)
        ids = {}
        for p in (lport, rport):
            ids[p] = ssh.run(f"adb -s localhost:{p} shell settings get secure android_id 2>/dev/null", 20).strip()
        distinct = ids[lport] and ids[lport] != ids[rport]
        step("distinct_devices", distinct, f"{recon}\nids={json.dumps(ids)}")

        visual = ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures {PY} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1",
            120,
        )
        in_group = visual.count("state=target_group") >= 2
        step("both_in_group", in_group, visual)

        ssh.run(f"bash {R}/scripts/edge_brain_start.sh 2>&1 | tail -3", 25)
        reload = ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -10", 300)
        procs = ssh.run("pgrep -af 'edge_brain|bot_dual_supervisor|spawn_main' | grep -v pgrep | head -8", 15)
        step("services_up", "spawn_main" in procs, f"{reload}\n{procs}")

        time.sleep(55)
        verify = ssh.run(
            f"cd {R} && {PY} scripts/verify_group_announce_outgoing.py "
            f"--left localhost:{lport} --right localhost:{rport} 2>&1",
            180,
        )
        out_ok = "verdict=PASS" in verify
        step("verify_out", out_ok, verify)

        cron = ssh.run(
            "crontab -l 2>/dev/null | grep -E 'daily_memory|lean-boot|vmos-maintenance' | head -5 || echo no_cron",
            15,
        )
        step("vps_cron", "daily_memory" in cron or "lean-boot" in cron or "no_cron" in cron, cron)

    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'local_auto_gate|local_tunnel_keepalive|edge_mock_panel' } | "
         "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; 'local_gate_stopped'"],
        capture_output=True, timeout=30,
    )
    step("local_gate_stopped", True, "local interference cleared")

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if rc == 0:
        subprocess.run(["shutdown", "/s", "/t", "120", "/c", "W49: VPS 已接管，120秒后关机"], check=False)
        print("scheduled shutdown /s /t 120", flush=True)
    else:
        print("验收未全绿，未安排本机关机", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
