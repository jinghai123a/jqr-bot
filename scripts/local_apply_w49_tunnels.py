#!/usr/bin/env python3
"""从 config/tunnel-creds.local.env 写 tunnel-*.env 并本机 paramiko 隧道 + adb。"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_tunnel.env_io import load_env_file, write_tunnel_env  # noqa: E402


def _side_cfg(side: str, raw: dict[str, str]) -> dict[str, str]:
    prefix = side.upper()
    ssh_cmd = raw.get(f"{prefix}_SSH_COMMAND", "").strip()
    ssh_pass = raw.get(f"{prefix}_SSH_PASS", "").strip()
    adb_cmd = raw.get(f"{prefix}_ADB_COMMAND", "").strip()
    port = raw.get(f"{prefix}_LOCAL_PORT", "").strip()
    host = raw.get(f"{prefix}_SSH_HOST", "").strip()
    bind = raw.get(f"{prefix}_TUNNEL_BIND", "").strip()
    if not ssh_cmd or not ssh_pass:
        raise SystemExit(f"missing {prefix}_SSH_COMMAND / {prefix}_SSH_PASS in tunnel-creds.local.env")
    if not port:
        import re

        m = re.search(r"-L\s+(\d+):", ssh_cmd)
        port = m.group(1) if m else ("61573" if side == "right" else "50185")
    if not adb_cmd:
        adb_cmd = f"adb connect localhost:{port}"
    if not host:
        from bot_tunnel.ssh_parse import parse_ssh_command

        host, _, _ = parse_ssh_command(ssh_cmd)
    return {
        "ssh_command": ssh_cmd,
        "ssh_pass": ssh_pass,
        "adb_command": adb_cmd,
        "port": port,
        "host": host,
        "bind": bind or ("195.114.193.237" if side == "right" else "195.114.193.136"),
    }


def main() -> int:
    creds_path = ROOT / "config" / "tunnel-creds.local.env"
    if not creds_path.exists():
        print(f"缺少 {creds_path}（已 gitignore，见 tunnel-creds.local.env.example）", file=sys.stderr)
        return 1
    raw = load_env_file(creds_path)

    for side in ("right", "left"):
        cfg = _side_cfg(side, raw)
        path = ROOT / "config" / f"tunnel-{side}.env"
        issued = datetime.now(tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
        write_tunnel_env(
            path,
            cfg["port"],
            cfg["host"],
            raw.get(f"{side.upper()}_SSH_PORT", "1824"),
            raw.get(f"{side.upper()}_SSH_USER", "s"),
            cfg["ssh_pass"],
            ssh_command=cfg["ssh_command"],
            adb_command=cfg["adb_command"],
            expire_minutes=raw.get("EXPIRE_MINUTES", "1440"),
            issued_at=issued,
            tunnel_bind_ip=cfg["bind"],
            header=f"# W49 manual OpenAPI local — {side} LOCAL_PORT={cfg['port']}",
        )
        print(f"wrote {path}")

    try:
        import paramiko  # noqa: F401
    except ImportError:
        import subprocess

        print("installing paramiko…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko>=3.4.0", "-q"])

    from scripts.edge_local_tunnels import connect_isolated_adb, connect_side

    ok_r = connect_side("right")
    ok_l = connect_side("left")
    connect_isolated_adb()
    return 0 if ok_r and ok_l else 1


if __name__ == "__main__":
    raise SystemExit(main())
