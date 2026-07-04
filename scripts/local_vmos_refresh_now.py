#!/usr/bin/env python3
"""本机 OpenAPI 续期 tunnel-*.env → paramiko 重连 + adb 验通（固定文档「手动立即刷新」）。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_tunnel.adb_probe import adb_probe_port  # noqa: E402
from bot_ops.config import _parse_env_file  # noqa: E402


def _ports() -> tuple[str, str]:
    env = _parse_env_file(ROOT / "config" / "bot-start.env")
    return (
        str(env.get("BOT_CLICKER_ADB_PORT") or "52840"),
        str(env.get("BOT_LISTENER_ADB_PORT") or "58433"),
    )


def _paramiko_reconnect() -> bool:
    from scripts.edge_local_tunnels import connect_isolated_adb, connect_side

    ok_r = connect_side("right")
    ok_l = connect_side("left")
    connect_isolated_adb()
    return ok_r and ok_l


def main() -> int:
    refresh = ROOT / "scripts" / "vmos-refresh-tunnels.py"
    if not (ROOT / "config" / "vmos-api.env").is_file():
        print("缺少 config/vmos-api.env — 跳过 OpenAPI，仅 paramiko 重连", file=sys.stderr)
        return 0 if _paramiko_reconnect() else 1

    print("=== OpenAPI refresh (no bash reconnect) ===", flush=True)
    r = subprocess.run(
        [sys.executable, str(refresh)],
        cwd=str(ROOT),
        timeout=300,
    )
    if r.returncode != 0:
        print(f"vmos-refresh exit={r.returncode}", file=sys.stderr)

    print("=== paramiko reconnect ===", flush=True)
    if not _paramiko_reconnect():
        return 1

    lport, rport = _ports()
    l_ok = adb_probe_port(lport)
    r_ok = adb_probe_port(rport)
    print(f"verify left:{lport}={l_ok} right:{rport}={r_ok}", flush=True)
    return 0 if l_ok and r_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
