#!/usr/bin/env python3
"""仅刷新左机 padCode 隧道 + 重启 daemon + 回群。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = "/home/bot/55chat-bot"
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402
from bot_tunnel import fetch_adb_with_backoff, parse_local_port, parse_ssh_command, write_tunnel_env  # noqa: E402
from scripts.vmos_api_client import VmosApiClient  # noqa: E402


def load_creds(ssh: VpsSSH) -> tuple[str, str]:
    raw = ssh.run(f"cat {R}/config/vmos-api.env")
    env: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    ak = env.get("VMOS_ACCESS_KEY") or env.get("ACCESS_KEY", "")
    sk = env.get("VMOS_SECRET_KEY") or env.get("SECRET_KEY", "")
    if not ak or not sk:
        raise RuntimeError("vmos-api.env missing keys")
    return ak, sk


def main() -> int:
    pads = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    left_code = str(pads["left"]["pad_code"])
    left_port = str(pads["left"]["local_port"])
    cfg = load_vps_config(ROOT)

    with VpsSSH(cfg) as ssh:
        ak, sk = load_creds(ssh)
        client = VmosApiClient(ak, sk, timeout=90)
        print(f"=== left get_adb {left_code} ===", flush=True)
        adb = fetch_adb_with_backoff(
            client,
            left_code,
            open_adb_first=False,
            attempts=4,
            wait_open_adb_tasks=False,
            wait_for_attempt=lambda i: min(20, 5 * i),
        )
        cmd = str(adb.get("command") or "")
        key = str(adb.get("key") or "")
        adb_cmd = str(adb.get("adb") or "")
        host, ssh_port, user = parse_ssh_command(cmd)
        api_port = parse_local_port(cmd, adb_cmd, left_port)
        print(f"  {host}:{ssh_port} local={api_port}", flush=True)

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
            tmp_path = Path(tmp.name)
            write_tunnel_env(
                tmp_path,
                api_port,
                host,
                ssh_port,
                user,
                key,
                ssh_command=cmd,
                adb_command=adb_cmd,
                expire_time=str(adb.get("expireTime") or ""),
                header="# edge_refresh_left_only.py",
            )
        try:
            ssh.sftp_put(str(tmp_path), f"{R}/config/tunnel-left.env")
        finally:
            os.unlink(tmp_path)

        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 120))
        print("=== adb ===")
        print(ssh.run("adb devices -l", 30))
        print("=== left model ===")
        print(ssh.run(f"adb -s localhost:{left_port} shell getprop ro.product.model", 20))
        print("=== restart daemon ===")
        print(ssh.run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -10", 120))
        print("=== recover ===")
        local_recover = ROOT / "scripts" / "recover_listener_now.py"
        if local_recover.is_file():
            ssh.sftp_put(str(local_recover), f"{R}/scripts/recover_listener_now.py")
        print(ssh.run(f"cd {R} && python3 scripts/recover_listener_now.py 2>&1", 180))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
