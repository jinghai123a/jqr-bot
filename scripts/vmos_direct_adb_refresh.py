#!/usr/bin/env python3
"""已知 padCode，跳过 list_pads，直接 get_adb + 写 VPS tunnel。"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from vmos_api_client import VmosApiClient  # noqa: E402

RIGHT, LEFT = "ATP6416I3I1E6KPM", "APP5AU4BB269OR35"


def ssh() -> paramiko.SSHClient:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)
    return s


def run(cmd: str, t: int = 120) -> str:
    s = ssh()
    _, o, e = s.exec_command(cmd, timeout=t)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    s.close()
    return out


def creds() -> tuple[str, str]:
    raw = run(f"cat {R}/config/vmos-api.env")
    env: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env["VMOS_ACCESS_KEY"], env["VMOS_SECRET_KEY"]


def parse_cmd(command: str) -> tuple[str, str, str]:
    port_m = re.search(r"-p\s+(\d+)", command)
    m = re.search(r"([\w-]+)@([\d.]+)", command)
    if not m:
        raise ValueError(command)
    return m.group(2), port_m.group(1) if port_m else "1824", m.group(1)


def write_env(side: str, port: str, host: str, ssh_port: str, user: str, password: str) -> None:
    body = (
        f"LOCAL_PORT={port}\nSSH_HOST={host}\nSSH_PORT={ssh_port}\n"
        f"SSH_USER={user}\nSSH_PASS={password}\n"
    )
    s = ssh()
    sftp = s.open_sftp()
    path = f"{R}/config/tunnel-{side}.env"
    with sftp.open(path, "w") as f:
        f.write(body)
    s.exec_command(f"chmod 600 {path}")
    s.close()


def fetch_adb(client: VmosApiClient, code: str) -> dict:
    for i in range(15):
        try:
            if i:
                w = min(90, 8 * (i + 1))
                print(f"  wait {w}s ...", flush=True)
                time.sleep(w)
            try:
                client.open_adb([code])
            except Exception as exc:
                print(f"  open_adb: {exc}", flush=True)
            return client.get_adb(code, enable=True, expire_minutes=10080)
        except Exception as exc:
            print(f"  get_adb {i+1}: {exc}", flush=True)
    raise RuntimeError(f"get_adb exhausted for {code}")


def main() -> int:
    ak, sk = creds()
    client = VmosApiClient(ak, sk, timeout=120)

    for side, code, port in (("right", RIGHT, "60478"), ("left", LEFT, "52718")):
        print(f"=== {side} {code} ===", flush=True)
        adb = fetch_adb(client, code)
        cmd = str(adb.get("command") or "")
        key = str(adb.get("key") or "")
        host, ssh_port, user = parse_cmd(cmd)
        print(f"  -> {host}:{ssh_port} user={user}", flush=True)
        write_env(side, port, host, ssh_port, user, key)

    print("\n=== reconnect ===", flush=True)
    print(run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 150))
    adb = run("adb devices -l")
    print(adb)
    if "60478" not in adb:
        return 1
    print(run(f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 150))
    if "bot_55chat_daemon.py" not in run("pgrep -af bot_55chat_daemon || true"):
        print(run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -5", 90))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
