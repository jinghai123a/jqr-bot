#!/usr/bin/env python3
"""Loop until left CLICKER :55612 online — bypass maintenance, local OpenAPI."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PADS_JSON = ROOT / "config" / "vmos-pads.json"
R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
sys.path.insert(0, str(ROOT))

from bot_ops.config import _parse_env_file, load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402
from bot_ops.vps_ports import port_device_online  # noqa: E402
from bot_tunnel import (  # noqa: E402
    fetch_adb_with_backoff,
    parse_local_port,
    parse_ssh_command,
    rewrite_adb_connect_port,
    rewrite_ssh_forward_port,
    write_tunnel_env,
)
from scripts.vmos_api.transport import mask_proxy_url, proxy_from_env  # noqa: E402
from scripts.vmos_api_client import VmosApiClient  # noqa: E402


def _ts() -> str:
    return datetime.now(tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _load_left() -> tuple[str, str, str]:
    pads = json.loads(PADS_JSON.read_text(encoding="utf-8")) if PADS_JSON.is_file() else {}
    left = pads.get("left") or {}
    return (
        str(left.get("pad_code") or "APPSA148R269OR35"),
        str(left.get("local_port") or "55612"),
        str(left.get("match_egress_ip") or ""),
    )


def _parse_kv_env(raw: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _load_proxy(ssh: VpsSSH | None = None) -> str:
    """Local env > config/vmos-proxy.env > config/vmos-api.env > VPS vmos-api.env."""
    local_extra: dict[str, str] = {}
    for path in (ROOT / "config" / "vmos-proxy.env", ROOT / "config" / "vmos-api.env"):
        local_extra.update(_parse_env_file(path))
    proxy = proxy_from_env(local_extra)
    if proxy:
        return proxy
    if ssh is not None:
        remote = _parse_kv_env(ssh.run(f"cat {R}/config/vmos-api.env", 30))
        proxy = proxy_from_env(remote)
        if proxy:
            return proxy
    return ""


def _vmos_creds(ssh: VpsSSH) -> tuple[str, str]:
    env = _parse_kv_env(ssh.run(f"cat {R}/config/vmos-api.env", 30))
    ak = env.get("VMOS_ACCESS_KEY") or env.get("VMOS_AK") or ""
    sk = env.get("VMOS_SECRET_KEY") or env.get("VMOS_SK") or ""
    if not ak or not sk:
        raise RuntimeError("missing vmos-api creds")
    return ak, sk


def _vmos_client(ssh: VpsSSH) -> VmosApiClient:
    proxy = _load_proxy(ssh)
    if proxy:
        print(f"  OpenAPI via proxy {mask_proxy_url(proxy)}", flush=True)
    else:
        print("  OpenAPI direct (set VMOS_API_PROXY in config/vmos-proxy.env)", flush=True)
    return VmosApiClient(*_vmos_creds(ssh), timeout=120, proxy=proxy or None)


def _push_left_env(ssh: VpsSSH, *, port: str, host: str, ssh_port: str, user: str, password: str,
                   ssh_command: str, adb_command: str, expire_time: str, bind_ip: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
        p = Path(tmp.name)
        write_tunnel_env(
            p, port, host, ssh_port, user, password,
            ssh_command=ssh_command, adb_command=adb_command, expire_time=expire_time,
            expire_minutes="1440", issued_at=_ts(), tunnel_bind_ip=bind_ip,
            header="# force left loop",
        )
    try:
        remote = f"{R}/config/tunnel-left.env"
        ssh.sftp_put(str(p), remote)
        ssh.run(f"chmod 600 {remote}", 15)
    finally:
        os.unlink(p)


def _one_attempt(ssh: VpsSSH, code: str, port: str, bind: str, attempt: int) -> bool:
    print(f"\n[{_ts()}] LEFT LOOP {attempt} {code} :{port}", flush=True)
    ssh.run(
        "pkill -9 -f vmos-refresh-tunnels.py 2>/dev/null || true; "
        f"rm -f {R}/data/vmos-refresh.lock {R}/logs/.vmos-refresh.lock; true",
        20,
    )
    try:
        client = _vmos_client(ssh)
        try:
            tasks = client.open_adb([code])
            client.wait_open_adb_tasks(tasks, timeout=180)
        except Exception as exc:
            print(f"  open_adb warn: {exc}", flush=True)
        adb = fetch_adb_with_backoff(
            client, code, open_adb_first=False, attempts=10,
            wait_for_attempt=lambda i: min(120, 15 * i),
        )
        cmd = rewrite_ssh_forward_port(str(adb.get("command") or ""), port)
        adb_cmd = rewrite_adb_connect_port(str(adb.get("adb") or ""), port)
        key = str(adb.get("key") or "")
        host, ssh_port, user = parse_ssh_command(cmd)
        _push_left_env(
            ssh, port=port, host=host, ssh_port=ssh_port, user=user, password=key,
            ssh_command=cmd, adb_command=adb_cmd,
            expire_time=str(adb.get("expireTime") or ""), bind_ip=bind,
        )
        print(f"  cred ok {host}:{ssh_port}", flush=True)
    except Exception as exc:
        print(f"  API error: {exc}", flush=True)

    print(ssh.run(f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -10", 120))
    out = ssh.run(f"adb -P 5039 devices -l; adb -P 5039 -s localhost:{port} shell echo OK 2>&1", 30)
    print(out)
    if not (port_device_online(out, port) and "OK" in out):
        return False
    print(ssh.run(f"cd {R} && {PY} scripts/vps_restart_left_only.py 2>&1 | tail -20", 360))
    smoke = ssh.run(
        f"set -a; . {R}/config/bot-start.env; set +a; "
        f"cd {R} && {PY} scripts/vps_force_left_out_now.py 2>&1",
        120,
    )
    print(smoke)
    return "OK:" in smoke or "announce visible" in smoke or "tunnel up" in smoke


def main() -> int:
    code, port, bind = _load_left()
    attempt = 0
    while True:
        attempt += 1
        try:
            with VpsSSH(load_vps_config(ROOT)) as ssh:
                if _one_attempt(ssh, code, port, bind, attempt):
                    print(f"[{_ts()}] LEFT_TUNNEL_OK")
                    return 0
        except Exception as exc:
            print(f"[{_ts()}] SSH/loop error: {exc}", flush=True)
        sleep_s = min(180, 20 * min(attempt, 10))
        print(f"[{_ts()}] left still down — retry in {sleep_s}s", flush=True)
        time.sleep(sleep_s)


if __name__ == "__main__":
    raise SystemExit(main())
