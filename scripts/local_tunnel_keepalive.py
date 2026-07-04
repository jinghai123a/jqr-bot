#!/usr/bin/env python3
"""本机隧道探活：adb probe → paramiko 重连 → 仍失败则 OpenAPI 续期（禁止定时 API cron）。"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import _parse_env_file  # noqa: E402
from bot_tunnel.adb_probe import adb_probe_port  # noqa: E402


def _ports() -> tuple[str, str]:
    env = _parse_env_file(ROOT / "config" / "bot-start.env")
    return (
        str(env.get("BOT_CLICKER_ADB_PORT") or "52840"),
        str(env.get("BOT_LISTENER_ADB_PORT") or "58433"),
    )


def _failed_sides() -> list[str]:
    lport, rport = _ports()
    failed: list[str] = []
    if not adb_probe_port(lport):
        failed.append("left")
    if not adb_probe_port(rport):
        failed.append("right")
    return failed


def _reconnect_paramiko(sides: list[str]) -> bool:
    from scripts.edge_local_tunnels import connect_isolated_adb, connect_side

    ok = True
    for side in sides:
        ok = connect_side(side) and ok
    connect_isolated_adb()
    return ok


def _apply_manual_creds() -> bool:
    script = ROOT / "scripts" / "local_apply_w49_tunnels.py"
    creds = ROOT / "config" / "tunnel-creds.local.env"
    if not creds.is_file():
        return False
    r = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        timeout=120,
    )
    return r.returncode == 0


def _refresh_openapi() -> bool:
    script = ROOT / "scripts" / "local_vmos_refresh_now.py"
    if not (ROOT / "config" / "vmos-api.env").is_file():
        return False
    r = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        timeout=360,
    )
    return r.returncode == 0


def run_cycle(*, verbose: bool = True, allow_openapi: bool = False) -> bool:
    failed = _failed_sides()
    if not failed:
        if verbose:
            lport, rport = _ports()
            print(f"[keepalive] OK left:{lport} right:{rport}", flush=True)
        return True

    lport, rport = _ports()
    print(f"[keepalive] FAIL sides={failed} left:{lport} right:{rport}", flush=True)

    if _reconnect_paramiko(failed) and not _failed_sides():
        print("[keepalive] paramiko reconnect OK", flush=True)
        return True

    if _apply_manual_creds() and not _failed_sides():
        print("[keepalive] manual creds reconnect OK", flush=True)
        return True

    if allow_openapi and _refresh_openapi() and not _failed_sides():
        print("[keepalive] OpenAPI refresh OK", flush=True)
        return True

    print("[keepalive] reconnect failed (OpenAPI: --allow-openapi or local_vmos_refresh_now.py)", flush=True)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="本机双隧道探活与自愈")
    ap.add_argument("--interval", type=int, default=60, help="探活间隔秒（仅 --hold）")
    ap.add_argument("--hold", action="store_true", help="循环探活不退出")
    ap.add_argument("--once", action="store_true", help="单次探活/自愈")
    ap.add_argument("--allow-openapi", action="store_true", help="paramiko/手动凭证失败后调 OpenAPI 续期")
    args = ap.parse_args()

    if args.once or not args.hold:
        ok = run_cycle(allow_openapi=args.allow_openapi)
        return 0 if ok else 1

    print(
        f"[keepalive] holding interval={args.interval}s ts={datetime.now(timezone.utc).isoformat()}",
        flush=True,
    )
    while True:
        run_cycle(verbose=False, allow_openapi=args.allow_openapi)
        time.sleep(max(15, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
