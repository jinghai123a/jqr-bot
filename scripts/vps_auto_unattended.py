#!/usr/bin/env python3
"""VPS 无人看守部署（用户使用.md 对齐）。

前提：双云机已在目标群界面（W49 手动进群）。
避坑：不 scp 本机 bot-start.env；per-side 隧道；禁 recover；禁 watchdog 风暴。
"""
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
ART = ROOT / "artifacts" / "vps-auto-unattended.json"
PY = f"{R}/.venv/bin/python3"

UPLOAD_FILES = (
    "bot_55chat_daemon.py",
    "bot_ops/nav_guard.py",
    "bot_ops/announce_audit.py",
    "scripts/verify_group_announce_outgoing.py",
    "scripts/vmos_visual_monitor.py",
    "scripts/patch_speed_env.py",
    "scripts/reconnect-dual-adb.sh",
    "config/vmos-pads.json",
    "config/pinned-coords.json",
)

UPLOAD_KB = (
    "config/55m-knowledge/ui-pages.json",
    "config/55m-knowledge/apis.json",
    "config/55m-knowledge/announce-templates.json",
    "config/55m-knowledge/chat-commands.json",
    "config/55m-knowledge/control-plane.json",
)

SHELL_SCRIPTS = (
    "reconnect-dual-adb.sh",
    "tunnel-left.sh",
    "tunnel-right.sh",
    "reload-dual-workers.sh",
    "edge_brain_start.sh",
)


def _local_preflight() -> None:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements-edge.txt")],
    )
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_nav_guard.py",
            "tests/test_jwt_auth.py",
            "tests/test_bot_ops_jwt.py",
            "tests/test_edge_brain.py",
            "-q",
            "--tb=line",
        ],
        cwd=str(ROOT),
    )
    subprocess.check_call(
        [sys.executable, "-m", "py_compile", str(ROOT / "bot_55chat_daemon.py")],
    )


def _pads_ports() -> tuple[str, str]:
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    return str(pads["left"]["local_port"]), str(pads["right"]["local_port"])


def _stop_local_interference() -> str:
    """停本机 gate/隧道占用，避免与 VPS 抢 ADB。"""
    ps = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -match 'local_auto_gate|local_tunnel_keepalive|bot_55chat_daemon|edge_mock_panel' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; "
            "Write-Output local_stopped",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return (ps.stdout or "") + (ps.stderr or "")


def main() -> int:
    report: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "standard": "docs/用户使用.md",
        "steps": [],
    }
    rc = 0
    lport, rport = _pads_ports()

    def step(name: str, ok: bool, detail: str) -> None:
        nonlocal rc
        if not ok:
            rc = 1
        report["steps"].append({"name": name, "ok": ok, "detail": detail[:5000]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}", flush=True)
        if detail.strip():
            print(detail[:1500], flush=True)

    print("=== Step0 local preflight ===", flush=True)
    try:
        _local_preflight()
        step("local_preflight", True, "pytest+py_compile OK")
    except subprocess.CalledProcessError as ex:
        step("local_preflight", False, str(ex))
        ART.parent.mkdir(parents=True, exist_ok=True)
        ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        print("=== Step1 stop VPS interference ===", flush=True)
        out = ssh.run(
            "pkill -f edge_adb_agent.py 2>/dev/null; "
            "pkill -f cloud_dual_watch 2>/dev/null; "
            "for t in vmos-dual-watchdog.timer vmos-adb-watchdog.timer vmos-adb-keepalive.timer; do "
            "  systemctl stop $t 2>/dev/null; systemctl disable $t 2>/dev/null; "
            "done; echo interference_stopped",
            40,
        )
        step("stop_interference", "interference_stopped" in out, out)

        print("=== Step2 upload code (no local bot-start.env) ===", flush=True)
        for rel in UPLOAD_FILES:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
        for rel in UPLOAD_KB:
            local = ROOT / rel
            if local.is_file():
                ssh.sftp_put(str(local), f"{R}/{rel.replace(chr(92), '/')}")
        crlf = " && ".join(
            f"sed -i 's/\\r$//' {R}/scripts/{s} 2>/dev/null; chmod +x {R}/scripts/{s} 2>/dev/null"
            for s in SHELL_SCRIPTS
        )
        out = ssh.run(f"{crlf}; echo upload_ok", 30)
        comp = ssh.run(f"{PY} -m py_compile {R}/bot_55chat_daemon.py {R}/scripts/verify_group_announce_outgoing.py", 60)
        step("upload_compile", "upload_ok" in out and not comp.strip().lower().startswith("traceback"), out + comp)

        print("=== Step3 env: manual-in-group + ms SLO ===", flush=True)
        env_lines = (
            "BOT_MANUAL_IN_GROUP=1",
            "BOT_EDGE_ADB_AGENT=0",
            "BOT_EDGE_AUTOJS6=0",
            "BOT_LISTENER_ZERO_NAV=1",
            f"BOT_LISTENER_ADB_PORT={rport}",
            f"BOT_CLICKER_ADB_PORT={lport}",
            "BOT_LISTENER_ANNOUNCE_VERIFY_MAX_MS=2000",
            "BOT_ANNOUNCE_LOOP_SEC=0.25",
        )
        for kv in env_lines:
            k, v = kv.split("=", 1)
            ssh.run(
                f"grep -q '^{k}=' {R}/config/bot-start.env 2>/dev/null && "
                f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || "
                f"echo '{k}={v}' >> {R}/config/bot-start.env",
                15,
            )
        out = ssh.run(f"{PY} {R}/scripts/patch_speed_env.py 2>&1; grep -E 'MANUAL|ADB_PORT|ANNOUNCE_VERIFY' {R}/config/bot-start.env | head -8", 30)
        step("env_patch", "BOT_MANUAL_IN_GROUP=1" in out, out)

        print("=== Step4 per-side tunnel reconnect (no full tear) ===", flush=True)
        out = ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1 | tail -20", 180)
        adb = ssh.run("adb devices -l 2>/dev/null", 20)
        ok_tunnel = lport in adb and rport in adb and "offline" not in adb.lower()
        step("tunnel_reconnect", ok_tunnel, f"{out}\n{adb}")

        print("=== Step5 verify already in group (no recover) ===", flush=True)
        visual = ssh.run(
            f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
            f"{PY} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1",
            120,
        )
        in_group = visual.count("state=target_group") >= 1 or "target_group" in visual
        step("in_group_check", in_group, visual)

        print("=== Step6 edge_brain + reload dual (skip recover) ===", flush=True)
        ssh.run(f"bash {R}/scripts/edge_brain_start.sh 2>&1 | tail -5", 30)
        health = ssh.run("curl -sf http://127.0.0.1:8790/health; echo", 15)
        reload = ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -15", 300)
        procs = ssh.run(
            "pgrep -af 'edge_brain|bot_dual_supervisor|spawn_main' | grep -v pgrep | head -8",
            20,
        )
        step(
            "reload_workers",
            '"ok"' in health.lower() or "true" in health.lower(),
            f"health={health}\n{reload}\n{procs}",
        )

        print("=== Step7 wait announce + OUT verify (用户使用 §〇) ===", flush=True)
        time.sleep(55)
        verify = ""
        verify_ok = False
        for attempt in range(3):
            verify = ssh.run(
                f"cd {R} && {PY} scripts/verify_group_announce_outgoing.py "
                f"--left 127.0.0.1:{lport} --right 127.0.0.1:{rport} 2>&1",
                180,
            )
            verify_ok = "verdict=PASS" in verify
            if verify_ok:
                break
            if attempt < 2:
                time.sleep(30)
        step("verify_out", verify_ok, verify)

    print("=== Step8 stop local interference ===", flush=True)
    local_stop = _stop_local_interference()
    step("local_stop", True, local_stop)

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {ART}", flush=True)

    if rc == 0:
        print("=== Step9 schedule local shutdown (120s) ===", flush=True)
        subprocess.run(
            ["shutdown", "/s", "/t", "120", "/c", "W49 AUTO: VPS 已接管，120秒后关机"],
            check=False,
        )
        step("shutdown_scheduled", True, "shutdown /s /t 120")
    else:
        print("VPS 验收未全绿，跳过本机关机", flush=True)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
