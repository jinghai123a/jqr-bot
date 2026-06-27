#!/usr/bin/env python3
"""已知 padCode，跳过 list_pads，直接 get_adb + 写 VPS tunnel。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST, PW, R = "46.183.27.174", "Aa112211@@785*", "/home/bot/55chat-bot"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_tunnel import (  # noqa: E402
    fetch_adb_with_backoff,
    parse_local_port,
    parse_ssh_command,
    write_tunnel_env,
)
from scripts.vmos_api_client import VmosApiClient  # noqa: E402

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


def write_env_remote(side: str, local_port: str, host: str, ssh_port: str, user: str, password: str, *, ssh_command: str = "", adb_command: str = "", expire_time: str = "") -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
        tmp_path = Path(tmp.name)
        write_tunnel_env(
            tmp_path,
            local_port,
            host,
            ssh_port,
            user,
            password,
            ssh_command=ssh_command,
            adb_command=adb_command,
            expire_time=expire_time,
            header=f"# auto-updated by vmos_direct_adb_refresh.py",
        )
    try:
        s = ssh()
        sftp = s.open_sftp()
        remote = f"{R}/config/tunnel-{side}.env"
        sftp.put(str(tmp_path), remote)
        s.exec_command(f"chmod 600 {remote}")
        sftp.close()
        s.close()
    finally:
        os.unlink(tmp_path)


def main() -> int:
    ak, sk = creds()
    client = VmosApiClient(ak, sk, timeout=120)

    for side, code, port in (("right", RIGHT, "60478"), ("left", LEFT, "52718")):
        print(f"=== {side} {code} ===", flush=True)
        adb = fetch_adb_with_backoff(client, code, open_adb_first=True, attempts=15)
        cmd = str(adb.get("command") or "")
        key = str(adb.get("key") or "")
        adb_cmd = str(adb.get("adb") or "")
        host, ssh_port, user = parse_ssh_command(cmd)
        api_port = parse_local_port(cmd, adb_cmd, port)
        print(f"  -> {host}:{ssh_port} user={user}", flush=True)
        write_env_remote(
            side,
            api_port,
            host,
            ssh_port,
            user,
            key,
            ssh_command=cmd,
            adb_command=adb_cmd,
            expire_time=str(adb.get("expireTime") or ""),
        )

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
