#!/usr/bin/env python3
"""V2 Gate 本地自动执行：隧道→edge_brain→mock panel→daemon→OUT 公告验收。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import _parse_env_file, load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402

ART = ROOT / "artifacts" / "local-auto-gate.json"
JWT_SECRET = os.environ.get("EDGE_BRAIN_JWT_SECRET", "w49-local-auto-gate-jwt-secret")
PROCS: list[subprocess.Popen] = []


def _load_env() -> None:
    for k, v in _parse_env_file(ROOT / "config" / "bot-start.env").items():
        os.environ.setdefault(k, v)
    os.environ.update(
        {
            "BOT_API_BASE": "http://127.0.0.1:3000",
            "BOT_PANEL_URL": "http://127.0.0.1:3000",
            "EDGE_BRAIN_JWT_SECRET": JWT_SECRET,
            "EDGE_MOCK_GROUP_LEFT": "苍井空测试",
            "EDGE_MOCK_GROUP_RIGHT": "苍井空测试",
            "BOT_TARGET_GROUP": "苍井空测试",
            "BOT_MANUAL_IN_GROUP": "0",
            "BOT_ADB_ISOLATED": "0",
        }
    )
    token_py = ROOT / "scripts" / "edge_issue_jwt.py"
    r = subprocess.run(
        [sys.executable, str(token_py)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
        timeout=30,
        cwd=str(ROOT),
    )
    for line in (r.stdout or "").splitlines():
        if line.startswith("EDGE_BRAIN_JWT="):
            os.environ["BOT_EDGE_BRAIN_JWT"] = line.split("=", 1)[1].strip()
            os.environ["EDGE_BRAIN_JWT"] = os.environ["BOT_EDGE_BRAIN_JWT"]
            break


def _spawn(cmd: list[str], *, name: str) -> subprocess.Popen:
    log = ROOT / "logs" / f"local-gate-{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    fh = log.open("w", encoding="utf-8")
    print(f"[spawn] {name} -> {log}", flush=True)
    p = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=os.environ.copy(),
        stdout=fh,
        stderr=subprocess.STDOUT,
    )
    PROCS.append(p)
    return p


def _health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _run(cmd: list[str], *, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=os.environ.copy(),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _vps_probe() -> dict[str, object]:
    out: dict[str, object] = {"ok": False}
    try:
        cfg = load_vps_config(ROOT)
        with VpsSSH(cfg) as ssh:
            R = cfg.bot_root
            health = ssh.run(
                f"curl -fsS http://127.0.0.1:8790/health 2>/dev/null || echo DOWN",
                15,
            )
            procs = ssh.run(
                f"pgrep -af 'edge_brain|bot_55chat_daemon|dual_supervisor' | grep -v pgrep | head -6",
                20,
            )
            verify = ssh.run(
                f"cd {R} && {R}/.venv/bin/python3 scripts/verify_group_announce_outgoing.py "
                f"--left 127.0.0.1:{cfg.clicker_adb_port} --right 127.0.0.1:{cfg.listener_adb_port} 2>&1 | tail -8",
                120,
            )
            out = {"ok": True, "health": health.strip(), "procs": procs.strip(), "verify": verify.strip()}
    except Exception as ex:
        out["error"] = str(ex)
    return out


def main() -> int:
    report: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "steps": [],
    }
    rc = 0

    def step(name: str, ok: bool, detail: str) -> None:
        nonlocal rc
        if not ok:
            rc = 1
        report["steps"].append({"name": name, "ok": ok, "detail": detail[:3000]})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}\n{detail[:800]}", flush=True)

    _load_env()

    print("=== Gate0 tunnels ===", flush=True)
    c0, o0 = _run(
        [sys.executable, str(ROOT / "scripts" / "local_apply_w49_tunnels.py")],
        timeout=120,
    )
    step("tunnel_apply", c0 == 0, o0)
    _spawn(
        [sys.executable, str(ROOT / "scripts" / "local_tunnel_keepalive.py"), "--hold", "--interval", "60"],
        name="tunnels-keepalive",
    )
    time.sleep(2)
    c, o = _run(
        [
            "adb",
            "connect",
            f"localhost:{os.environ['BOT_LISTENER_ADB_PORT']}",
        ],
        timeout=20,
    )
    c2, o2 = _run(
        ["adb", "connect", f"localhost:{os.environ['BOT_CLICKER_ADB_PORT']}"],
        timeout=20,
    )
    step("tunnels", True, (o + o2).strip())

    print("=== Gate1 services ===", flush=True)
    _spawn([sys.executable, str(ROOT / "scripts" / "edge_mock_panel.py")], name="panel")
    _spawn([sys.executable, "-m", "edge_brain"], name="edge-brain")
    _spawn([sys.executable, str(ROOT / "mock_gateway.py")], name="gateway")
    time.sleep(2.5)
    step("edge_brain_health", _health("http://127.0.0.1:8790/health"), "8790/health")
    step("panel_health", _health("http://127.0.0.1:3000/api/bots"), "3000/api/bots")

    print("=== Gate2 recover right in group ===", flush=True)
    c, o = _run(
        [
            sys.executable,
            str(ROOT / "bot_55chat_daemon.py"),
            "--recover-group",
            f"localhost:{os.environ['BOT_LISTENER_ADB_PORT']}",
        ],
        timeout=90,
    )
    step("recover_right_group", c == 0 and "ok" in o.lower(), o)

    print("=== Gate3 daemon ===", flush=True)
    _spawn([sys.executable, str(ROOT / "bot_55chat_daemon.py")], name="daemon")
    print("waiting 50s for announce loop...", flush=True)
    time.sleep(50)

    print("=== Gate4 verify OUT ===", flush=True)
    for attempt in range(3):
        c, o = _run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_group_announce_outgoing.py"),
                "--left",
                f"localhost:{os.environ['BOT_CLICKER_ADB_PORT']}",
                "--right",
                f"localhost:{os.environ['BOT_LISTENER_ADB_PORT']}",
            ],
            timeout=120,
        )
        if c == 0:
            step("verify_outgoing_announce", True, o)
            break
        if attempt < 2:
            time.sleep(25)
    else:
        step("verify_outgoing_announce", False, o)

    print("=== VPS probe ===", flush=True)
    vps = _vps_probe()
    report["vps"] = vps
    step("vps_probe", bool(vps.get("ok")), json.dumps(vps, ensure_ascii=False)[:1200])

    ART.parent.mkdir(parents=True, exist_ok=True)
    ART.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report -> {ART}", flush=True)

    for p in PROCS:
        try:
            p.terminate()
        except Exception:
            pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
