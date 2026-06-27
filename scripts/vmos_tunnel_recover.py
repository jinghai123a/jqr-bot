#!/usr/bin/env python3
"""VPS 上执行：VMOS get_adb → 更新 tunnel env → reconnect → recover。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_tunnel import (  # noqa: E402
    adb_probe_port,
    fetch_adb_with_backoff,
    load_env_file,
    parse_local_port,
    parse_ssh_command,
    write_tunnel_env,
)
from scripts.vmos_api_client import VmosApiClient  # noqa: E402

RIGHT, LEFT = "ATP6416I3I1E6KPM", "APP5AU4BB269OR35"


def load_api() -> VmosApiClient:
    env = load_env_file(ROOT / "config" / "vmos-api.env")
    return VmosApiClient(env["VMOS_ACCESS_KEY"], env["VMOS_SECRET_KEY"], timeout=20)


def main() -> int:
    client = load_api()
    for side, code, port in (("right", RIGHT, "60478"), ("left", LEFT, "52718")):
        if adb_probe_port(port):
            print(f"[{side}] adb :{port} already online", flush=True)
            continue
        print(f"[{side}] fetching adb for {code}", flush=True)
        adb = fetch_adb_with_backoff(
            client,
            code,
            open_adb_first=False,
            attempts=20,
            wait_open_adb_tasks=False,
            wait_for_attempt=lambda i: min(120, 45 + 12 * (i - 1)),
        )
        cmd = str(adb.get("command") or "")
        key = str(adb.get("key") or "")
        adb_cmd = str(adb.get("adb") or "")
        if not cmd or not key:
            print(f"[{side}] bad adb response", adb, flush=True)
            return 1
        host, ssh_port, user = parse_ssh_command(cmd)
        api_port = parse_local_port(cmd, adb_cmd, port)
        print(f"[{side}] new tunnel {host}:{ssh_port}", flush=True)
        write_tunnel_env(
            ROOT / "config" / f"tunnel-{side}.env",
            api_port,
            host,
            ssh_port,
            user,
            key,
            ssh_command=cmd,
            adb_command=adb_cmd,
            expire_time=str(adb.get("expireTime") or ""),
            header="# auto-updated by vmos_tunnel_recover.py",
        )

    print("=== reconnect ===", flush=True)
    subprocess.run(["bash", str(ROOT / "scripts/reconnect-dual-adb.sh")], check=False)
    out = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True)
    print(out.stdout)
    if "60478" not in out.stdout or not adb_probe_port("60478"):
        return 1

    print("=== recover listener ===", flush=True)
    r = subprocess.run(
        ["python3", str(ROOT / "scripts/recover_listener_now.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    print(r.stdout)
    print(r.stderr)
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
