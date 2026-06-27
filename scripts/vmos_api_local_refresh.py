#!/usr/bin/env python3
"""从本机调 VMOS API（绕过 VPS IP 封禁/限流），成功后写回 VPS tunnel env 并重连。"""
from __future__ import annotations

import os
import sys
import time
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


def ssh_run(cmd: str, t: int = 120) -> str:
    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(HOST, username="root", password=PW, timeout=30)
    _, o, e = s.exec_command(cmd, timeout=t)
    out = (o.read() + e.read()).decode("utf-8", "replace")
    s.close()
    return out


def load_vmos_creds() -> tuple[str, str]:
    raw = ssh_run(f"cat {R}/config/vmos-api.env")
    env: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    ak = env.get("VMOS_ACCESS_KEY") or env.get("ACCESS_KEY", "")
    sk = env.get("VMOS_SECRET_KEY") or env.get("SECRET_KEY", "")
    if not ak or not sk:
        raise RuntimeError("vmos-api.env 缺少 ACCESS_KEY/SECRET_KEY")
    return ak, sk


def write_tunnel_on_vps(
    side: str,
    local_port: str,
    host: str,
    port: str,
    user: str,
    password: str,
    *,
    ssh_command: str = "",
    adb_command: str = "",
    expire_time: str = "",
) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
        tmp_path = Path(tmp.name)
        write_tunnel_env(
            tmp_path,
            local_port,
            host,
            port,
            user,
            password,
            ssh_command=ssh_command,
            adb_command=adb_command,
            expire_time=expire_time,
            header="# auto-updated by vmos_api_local_refresh.py",
        )
    try:
        remote = f"{R}/config/tunnel-{side}.env"
        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(HOST, username="root", password=PW, timeout=30)
        sftp = s.open_sftp()
        sftp.put(str(tmp_path), remote)
        s.exec_command(f"chmod 600 {remote}")
        s.close()
    finally:
        os.unlink(tmp_path)


def main() -> int:
    ak, sk = load_vmos_creds()
    client = VmosApiClient(ak, sk, timeout=90)

    print("=== list_pads (local IP) ===", flush=True)
    pads: list[dict] = []
    for i in range(8):
        try:
            pads = client.list_pads(rows=50)
            print(f"  got {len(pads)} pads", flush=True)
            break
        except Exception as exc:
            print(f"  list attempt {i+1}: {exc}", flush=True)
            time.sleep(15 * (i + 1))
    if not pads:
        print("  list_pads unavailable — use hardcoded padCode", flush=True)

    right_code = "ATP6416I3I1E6KPM"
    left_code = "APP5AU4BB269OR35"

    sides = (
        ("right", right_code, "60478"),
        ("left", left_code, "52718"),
    )
    ok_ports: list[str] = []
    for side, code, port in sides:
        print(f"\n=== get_adb {side} {code} ===", flush=True)
        try:
            client.open_adb([code])
        except Exception as exc:
            print(f"  open_adb warn: {exc}", flush=True)
        adb = fetch_adb_with_backoff(
            client,
            code,
            open_adb_first=False,
            wait_for_attempt=lambda i: min(120, 10 * (2 ** min(i - 1, 4))),
        )
        command = str(adb.get("command") or "")
        key = str(adb.get("key") or "")
        adb_cmd = str(adb.get("adb") or "")
        if not command or not key:
            print(f"FAIL: bad adb response keys={list(adb.keys())}", flush=True)
            return 1
        host, ssh_port, user = parse_ssh_command(command)
        api_port = parse_local_port(command, adb_cmd, port)
        print(f"  host={host}:{ssh_port} user={user} expire={adb.get('expireTime')}", flush=True)
        write_tunnel_on_vps(
            side,
            api_port,
            host,
            ssh_port,
            user,
            key,
            ssh_command=command,
            adb_command=adb_cmd,
            expire_time=str(adb.get("expireTime") or ""),
        )
        ok_ports.append(port)

    if not ok_ports:
        print("FAIL: no tunnel credentials updated", flush=True)
        return 1

    print("\n=== reconnect tunnels on VPS ===", flush=True)
    out = ssh_run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 120)
    print(out)

    adb = ssh_run("adb devices -l")
    print("=== adb ===")
    print(adb)

    ok = all(p in adb for p in ok_ports)
    if ok:
        print(ssh_run(f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 150))
        daemon = ssh_run("pgrep -af bot_55chat_daemon || true")
        if "bot_55chat_daemon.py" not in daemon:
            print(ssh_run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -6", 90))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
