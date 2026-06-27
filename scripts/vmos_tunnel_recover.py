#!/usr/bin/env python3
"""VPS 上执行：VMOS get_adb → 更新 tunnel env → reconnect → recover。"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from vmos_api_client import VmosApiClient  # noqa: E402

RIGHT, LEFT = "ATP6416I3I1E6KPM", "APP5AU4BB269OR35"
R = str(ROOT)


def load_api() -> VmosApiClient:
    env: dict[str, str] = {}
    for line in Path(f"{R}/config/vmos-api.env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return VmosApiClient(env["VMOS_ACCESS_KEY"], env["VMOS_SECRET_KEY"], timeout=20)


def parse_cmd(command: str) -> tuple[str, str, str]:
    port_m = re.search(r"-p\s+(\d+)", command)
    m = re.search(r"([\w-]+)@([\d.]+)", command)
    if not m:
        raise ValueError(command)
    return m.group(2), port_m.group(1) if port_m else "1824", m.group(1)


def write_env(side: str, port: str, host: str, ssh_port: str, user: str, password: str) -> None:
    path = Path(f"{R}/config/tunnel-{side}.env")
    path.write_text(
        f"LOCAL_PORT={port}\nSSH_HOST={host}\nSSH_PORT={ssh_port}\n"
        f"SSH_USER={user}\nSSH_PASS={password}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)


def adb_ok(port: str) -> bool:
    r = subprocess.run(
        ["adb", "-s", f"127.0.0.1:{port}", "shell", "echo", "OK"],
        capture_output=True, text=True, timeout=12,
    )
    return r.returncode == 0 and "OK" in (r.stdout or "")


def fetch_adb(client: VmosApiClient, code: str) -> dict:
    last: Exception | None = None
    for i in range(20):
        try:
            return client.get_adb(code, enable=True, expire_minutes=10080, retries=1)
        except Exception as exc:
            last = exc
            wait = min(120, 45 + 12 * i)
            print(f"  get_adb {i+1}/20: {exc} — sleep {wait}s", flush=True)
            time.sleep(wait)
    raise last or RuntimeError("get_adb failed")


def main() -> int:
    client = load_api()
    for side, code, port in (("right", RIGHT, "60478"), ("left", LEFT, "52718")):
        if adb_ok(port):
            print(f"[{side}] adb :{port} already online", flush=True)
            continue
        print(f"[{side}] fetching adb for {code}", flush=True)
        adb = fetch_adb(client, code)
        cmd = str(adb.get("command") or "")
        key = str(adb.get("key") or "")
        if not cmd or not key:
            print(f"[{side}] bad adb response", adb, flush=True)
            return 1
        host, ssh_port, user = parse_cmd(cmd)
        print(f"[{side}] new tunnel {host}:{ssh_port}", flush=True)
        write_env(side, port, host, ssh_port, user, key)

    print("=== reconnect ===", flush=True)
    subprocess.run(["bash", f"{R}/scripts/reconnect-dual-adb.sh"], check=False)
    out = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True)
    print(out.stdout)
    if "60478" not in out.stdout or not adb_ok("60478"):
        return 1

    print("=== recover listener ===", flush=True)
    r = subprocess.run(
        ["python3", f"{R}/scripts/recover_listener_now.py"],
        cwd=R, capture_output=True, text=True, timeout=180,
    )
    print(r.stdout)
    print(r.stderr)
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
