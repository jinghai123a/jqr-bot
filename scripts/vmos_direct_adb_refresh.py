#!/usr/bin/env python3
"""已知 padCode，跳过 list_pads，直接 get_adb + 写 VPS tunnel。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PADS_JSON = ROOT / "config" / "vmos-pads.json"
R = "/home/bot/55chat-bot"
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_tunnel import (  # noqa: E402
    fetch_adb_with_backoff,
    parse_local_port,
    parse_ssh_command,
    write_tunnel_env,
)
from scripts.vmos_api_client import VmosApiClient  # noqa: E402


def ssh_run(cmd: str, t: int = 120) -> str:
    cfg = load_vps_config(ROOT)
    import paramiko

    s = paramiko.SSHClient()
    s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    s.connect(cfg.host, username=cfg.user, password=cfg.password, timeout=30)
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


def write_env_remote(
    side: str,
    local_port: str,
    host: str,
    ssh_port: str,
    user: str,
    password: str,
    *,
    ssh_command: str = "",
    adb_command: str = "",
    expire_time: str = "",
) -> None:
    import tempfile

    import paramiko

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
            header="# auto-updated by vmos_direct_adb_refresh.py",
        )
    try:
        cfg = load_vps_config(ROOT)
        s = paramiko.SSHClient()
        s.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        s.connect(cfg.host, username=cfg.user, password=cfg.password, timeout=30)
        sftp = s.open_sftp()
        remote = f"{R}/config/tunnel-{side}.env"
        sftp.put(str(tmp_path), remote)
        s.exec_command(f"chmod 600 {remote}")
        sftp.close()
        s.close()
    finally:
        os.unlink(tmp_path)


def load_sides() -> tuple[tuple[str, str, str], tuple[str, str, str]]:
    pads_cfg = json.loads(PADS_JSON.read_text(encoding="utf-8")) if PADS_JSON.is_file() else {}
    right_code = str((pads_cfg.get("right") or {}).get("pad_code") or "ATP6416I3I1E6KPM")
    left_code = str((pads_cfg.get("left") or {}).get("pad_code") or "APPSA148R269OR35")
    right_port = str((pads_cfg.get("right") or {}).get("local_port") or "58433")
    left_port = str((pads_cfg.get("left") or {}).get("local_port") or "52840")
    return ("right", right_code, right_port), ("left", left_code, left_port)


def main() -> int:
    ak, sk = load_vmos_creds()
    client = VmosApiClient(ak, sk, timeout=120)
    right_side, left_side = load_sides()
    ok_ports: list[str] = []

    for side, code, port in (right_side, left_side):
        print(f"=== {side} {code} port={port} ===", flush=True)
        try:
            client.open_adb([code])
        except Exception as exc:
            print(f"  open_adb warn: {exc}", flush=True)
        adb = fetch_adb_with_backoff(
            client,
            code,
            open_adb_first=False,
            attempts=6,
            wait_open_adb_tasks=False,
            wait_for_attempt=lambda i: min(30, 5 * i),
        )
        cmd = str(adb.get("command") or "")
        key = str(adb.get("key") or "")
        adb_cmd = str(adb.get("adb") or "")
        if not cmd or not key:
            print(f"FAIL: bad adb response keys={list(adb.keys())}", flush=True)
            return 1
        host, ssh_port, user = parse_ssh_command(cmd)
        api_port = parse_local_port(cmd, adb_cmd, port)
        print(f"  -> {host}:{ssh_port} user={user} local={api_port}", flush=True)
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
        ok_ports.append(port)

    print("\n=== reconnect ===", flush=True)
    print(ssh_run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 150))
    adb = ssh_run("adb devices -l")
    print(adb)
    if not all(p in adb for p in ok_ports):
        return 1
    print(ssh_run(f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 150))
    if "bot_55chat_daemon.py" not in ssh_run("pgrep -af bot_55chat_daemon || true"):
        print(ssh_run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -5", 90))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
