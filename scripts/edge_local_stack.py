#!/usr/bin/env python3
"""
纯本地 + 云机全栈（不经 VPS 执行业务）：
  pytest → mock panel :3000 → edge_brain :8790 → 本机隧道 → adb reverse → AutoJs6/edge_adb_agent

与 APS 同环境：先跑 edge_sync_aps_parity.py 拉 board_capture / pinned-coords。
成功后一键：edge_deploy_aps.py（与 edge_auto_all 的 VPS 段相同）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROCS: list[subprocess.Popen[bytes]] = []


def _parse_env(path: Path) -> dict[str, str]:
    from bot_ops.config import _parse_env_file
    return _parse_env_file(path)


def parity_report() -> list[str]:
    gaps: list[str] = []
    need = [
        ROOT / "config" / "bot-start.env",
        ROOT / "config" / "tunnel-left.env",
        ROOT / "config" / "tunnel-right.env",
        ROOT / "config" / "pinned-coords.json",
        ROOT / "config" / "vmos-api.env",
    ]
    for p in need:
        if not p.is_file():
            gaps.append(f"missing {p.relative_to(ROOT)}")
    if not (ROOT / "board_capture.py").is_file():
        gaps.append("missing board_capture.py (run: python scripts/edge_sync_aps_parity.py)")
    try:
        subprocess.run(["adb", "version"], capture_output=True, timeout=5, check=True)
    except Exception:
        gaps.append("adb not in PATH (Android platform-tools)")
    return gaps


def run_pytest() -> None:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements-edge.txt")],
    )
    subprocess.check_call(
        [sys.executable, "-m", "pytest", "tests/test_edge_brain.py", "tests/test_clicker_settle.py", "-q"],
        cwd=str(ROOT),
    )


def start_proc(cmd: list[str], *, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    merged = {**os.environ, **(env or {})}
    p = subprocess.Popen(cmd, cwd=str(ROOT), env=merged)
    PROCS.append(p)
    return p


def wait_health(url: str, sec: float = 20.0) -> bool:
    deadline = time.time() + sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def adb_reverse_and_push() -> None:
    env = _parse_env(ROOT / "config" / "bot-start.env")
    lserver = env.get("BOT_CLICKER_ADB_SERVER_PORT", "5039")
    rserver = env.get("BOT_LISTENER_ADB_SERVER_PORT", "5038")
    lport = env.get("BOT_CLICKER_ADB_PORT", "52840")
    rport = env.get("BOT_LISTENER_ADB_PORT", "58433")
    pairs = (
        (lserver, lport, "settle-left"),
        (rserver, rport, "listener-right"),
    )
    for srv, port, side in pairs:
        serial = f"127.0.0.1:{port}"
        subprocess.run(["adb", "-P", srv, "-s", serial, "reverse", "tcp:8790", "tcp:8790"], check=False, timeout=15)
        remote_dir = f"/sdcard/Scripts/w49-{side}"
        subprocess.run(["adb", "-P", srv, "-s", serial, "shell", "mkdir", "-p", remote_dir], check=False, timeout=15)
        for name in ("edge_config.json", f"{'settle_left' if 'left' in side else 'listener_right'}.js"):
            local = ROOT / "edge_android" / side / name
            if local.is_file():
                subprocess.run(["adb", "-P", srv, "-s", serial, "push", str(local), f"{remote_dir}/{name}"], check=False, timeout=60)


def start_agent_windows() -> None:
    if sys.platform != "win32":
        start_proc([sys.executable, str(ROOT / "scripts" / "edge_adb_agent.py")], env={
            "EDGE_BRAIN_URL": "http://127.0.0.1:8790",
            "EDGE_BRAIN_JWT_SECRET": "w49-edge-jwt-secret-dev-only",
            "BOT_PANEL_URL": "http://127.0.0.1:3000",
        })
        return
    # Windows: fcntl 桩后启 agent
    wrapper = ROOT / "scripts" / "_edge_agent_win.py"
    wrapper.write_text(
        'import sys\nfrom unittest import mock\nsys.modules.setdefault("fcntl", mock.MagicMock())\n'
        f'sys.path.insert(0, r"{ROOT}")\n'
        'import runpy\nrunpy.run_path(r"' + str(ROOT / "scripts" / "edge_adb_agent.py").replace("\\", "\\\\") + '", run_name="__main__")\n',
        encoding="utf-8",
    )
    start_proc([sys.executable, str(wrapper)], env={
        "EDGE_BRAIN_URL": "http://127.0.0.1:8790",
        "EDGE_BRAIN_JWT_SECRET": "w49-edge-jwt-secret-dev-only",
        "BOT_PANEL_URL": "http://127.0.0.1:3000",
    })


def stack_up(*, agent: bool) -> int:
    gaps = parity_report()
    if gaps:
        print("PARITY_GAPS:")
        for g in gaps:
            print(f"  - {g}")
        print("fix gaps before E2E (sync: python scripts/edge_sync_aps_parity.py)")
    run_pytest()
    env_brain = {
        "EDGE_BRAIN_HOST": "0.0.0.0",
        "EDGE_BRAIN_PORT": "8790",
        "EDGE_BRAIN_JWT_SECRET": "w49-edge-jwt-secret-dev-only",
    }
    start_proc([sys.executable, str(ROOT / "scripts" / "edge_mock_panel.py")])
    start_proc([sys.executable, "-m", "edge_brain"], env=env_brain)
    if not wait_health("http://127.0.0.1:8790/health"):
        print("edge_brain failed to start", file=sys.stderr)
        return 1
    if not wait_health("http://127.0.0.1:3000/api/bots"):
        print("mock panel failed", file=sys.stderr)
        return 1
    tun_rc = subprocess.call([sys.executable, str(ROOT / "scripts" / "edge_local_tunnels.py")], cwd=str(ROOT))
    if tun_rc != 0:
        print("tunnel FAIL — check config/tunnel-*.env or: python scripts/vmos-refresh-tunnels.py --reconnect")
        return 1
    adb_reverse_and_push()
    if agent:
        start_agent_windows()
    print("LOCAL_STACK_OK brain=:8790 panel=:3000 tunnels=52840/58433")
    print("E2E: 等 warn 窗看群聊；成功后: python scripts/edge_deploy_aps.py")
    if "--detach" not in sys.argv:
        print("Ctrl+C 停止")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="仅 parity + pytest")
    ap.add_argument("--detach", action="store_true", help="启动后退出（进程后台）")
    ap.add_argument("--no-agent", action="store_true", help="仅 brain+AutoJs6，不启 edge_adb_agent")
    args = ap.parse_args()
    if args.check:
        gaps = parity_report()
        if gaps:
            for g in gaps:
                print(g)
            return 1
        run_pytest()
        print("LOCAL_CHECK_OK")
        return 0
    try:
        return stack_up(agent=not args.no_agent)
    finally:
        for p in PROCS:
            p.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
