#!/usr/bin/env python3
"""本机调 VMOS API 刷新左机凭证 → 写 VPS tunnel-left.env → 重连。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bot_ops.config import load_vps_config
from bot_ops.ssh_client import VpsSSH
from bot_tunnel import (
    fetch_adb_with_backoff,
    load_env_file,
    parse_local_port,
    parse_ssh_command,
    rewrite_adb_connect_port,
    rewrite_ssh_forward_port,
    write_tunnel_env,
)
from vmos_api_client import VmosApiClient

R = "/home/bot/55chat-bot"
LEFT_PORT = "52840"


def main() -> int:
    cfg = load_vps_config(ROOT)
    with VpsSSH(cfg) as ssh:
        api_raw = ssh.run(f"cat {R}/config/vmos-api.env", 15)
        pads_raw = ssh.run(f"cat {R}/config/vmos-pads.json 2>/dev/null || echo '{{}}'", 15)
    api_env: dict[str, str] = {}
    for line in api_raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            api_env[k.strip()] = v.strip().strip('"').strip("'")
    ak = api_env.get("VMOS_ACCESS_KEY") or api_env.get("VMOS_AK", "")
    sk = api_env.get("VMOS_SECRET_KEY") or api_env.get("VMOS_SK", "")
    if not ak or not sk:
        print("FAIL: missing VMOS keys")
        return 1
    pads_cfg = json.loads(pads_raw or "{}")
    left_code = str((pads_cfg.get("left") or {}).get("pad_code") or "").strip()
    if not left_code:
        print("FAIL: missing left pad_code in vmos-pads.json")
        return 1

    client = VmosApiClient(ak, sk, timeout=90)
    print(f"=== open_adb + get_adb left {left_code} ===")
    try:
        tasks = client.open_adb([left_code])
        client.wait_open_adb_tasks(tasks)
    except Exception as exc:
        print(f"open_adb warn: {exc}")
    adb = fetch_adb_with_backoff(client, left_code, open_adb_first=True, attempts=10)
    command = str(adb.get("command") or "")
    key = str(adb.get("key") or "")
    adb_cmd = str(adb.get("adb") or "")
    if not command or not key:
        print("FAIL: incomplete adb response", adb)
        return 1
    host, ssh_port, user = parse_ssh_command(command)
    command = rewrite_ssh_forward_port(command, LEFT_PORT)
    adb_cmd = rewrite_adb_connect_port(adb_cmd, LEFT_PORT) if adb_cmd else f"adb connect localhost:{LEFT_PORT}"
    print(f"host={host}:{ssh_port} expire={adb.get('expireTime')}")

    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
        tmp_path = Path(tmp.name)
        write_tunnel_env(
            tmp_path,
            LEFT_PORT,
            host,
            ssh_port,
            user,
            key,
            ssh_command=command,
            adb_command=adb_cmd,
            expire_time=str(adb.get("expireTime") or ""),
            header="# auto-updated by local_left_vmos_refresh.py",
        )
    try:
        with VpsSSH(cfg) as ssh:
            ssh.sftp_put(str(tmp_path), f"{R}/config/tunnel-left.env")
            ssh.run(f"chmod 600 {R}/config/tunnel-left.env", 10)
            ssh.run(f"pkill -f 'ssh.*{LEFT_PORT}:' 2>/dev/null || true", 10)
            time.sleep(2)
            print("=== tunnel-left.sh ===")
            ssh.run(f"sh -c 'bash {R}/scripts/tunnel-left.sh >> {R}/logs/tunnel-left.log 2>&1 </dev/null &'", 15)
            for i in range(20):
                time.sleep(5)
                out = ssh.run("adb devices 2>/dev/null", 12)
                print(f"[{i+1}] {out.strip()}")
                if f"localhost:{LEFT_PORT}\tdevice" in out or f"127.0.0.1:{LEFT_PORT}\tdevice" in out:
                    print("LEFT ONLINE")
                    py = f"{R}/.venv/bin/python3"
                    code = (
                        "from bot_ops.ephemeral_burn import _mediastore_image_count, purge_gallery_bot_images; "
                        f"s='localhost:{LEFT_PORT}'; "
                        "print('before', _mediastore_image_count(s)); "
                        "print('purged', purge_gallery_bot_images(s)); "
                        "print('after', _mediastore_image_count(s))"
                    )
                    print(ssh.run(f"cd {R} && {py} -c \"{code}\"", 300))
                    return 0
    finally:
        os.unlink(tmp_path)
    print("WARN: left still offline")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
