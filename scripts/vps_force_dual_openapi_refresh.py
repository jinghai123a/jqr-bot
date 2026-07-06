#!/usr/bin/env python3
"""Push VMOS creds + force OpenAPI refresh (long timeout) + dual tunnel."""
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bot_ops.config import _parse_env_file, load_vps_config
from bot_ops.deploy_secrets import push_runtime_secrets
from bot_ops.ssh_client import VpsSSH
from bot_ops.vps_ports import dual_adb_online, dual_adb_ports
from bot_tunnel import (
    fetch_adb_with_backoff,
    parse_ssh_command,
    refresh_side_credentials,
    resolve_pad_code,
    write_tunnel_env,
)
from bot_tunnel.daemon import build_daemon_sides
from bot_tunnel.ssh_parse import rewrite_adb_connect_port, rewrite_ssh_forward_port
from scripts.vmos_api.transport import mask_proxy_url, proxy_from_env
from vmos_api_client import VmosApiClient

R = "/home/bot/55chat-bot"
BJ = ZoneInfo("Asia/Shanghai")


def _ts() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S")


def _ensure_local_vmos_api() -> dict[str, str]:
    env = _parse_env_file(ROOT / "config" / "vmos-api.env")
    doc = ROOT / "config" / "本地-VMOS-开发者凭证.md"
    if doc.is_file():
        text = doc.read_text(encoding="utf-8")
        for label, key in (
            ("Access Key ID", "VMOS_ACCESS_KEY"),
            ("Secret Access Key", "VMOS_SECRET_KEY"),
        ):
            marker = f"| {label} | `"
            if marker in text:
                start = text.index(marker) + len(marker)
                end = text.index("`", start)
                val = text[start:end].strip()
                if val and (not env.get(key) or len(env.get(key, "")) < len(val)):
                    env[key] = val
    ak = (env.get("VMOS_ACCESS_KEY") or "").strip()
    sk = (env.get("VMOS_SECRET_KEY") or "").strip()
    cb = (env.get("VMOS_CALLBACK_URL") or "http://195.114.193.136:3000/api/vmos/callback").strip()
    if not ak or not sk:
        raise RuntimeError("VMOS_ACCESS_KEY / VMOS_SECRET_KEY missing")
    if len(sk) < 20:
        raise RuntimeError(f"VMOS_SECRET_KEY too short ({len(sk)} chars)")
    (ROOT / "config" / "vmos-api.env").write_text(
        f"# VMOS Cloud API — synced {_ts()}\n"
        f"VMOS_ACCESS_KEY={ak}\n"
        f"VMOS_SECRET_KEY={sk}\n"
        f"VMOS_CALLBACK_URL={cb}\n",
        encoding="utf-8",
    )
    return {"VMOS_ACCESS_KEY": ak, "VMOS_SECRET_KEY": sk, "VMOS_CALLBACK_URL": cb}


def _client(env: dict[str, str]) -> VmosApiClient:
    extra = _parse_env_file(ROOT / "config" / "vmos-proxy.env")
    proxy = proxy_from_env({**extra, **env})
    if proxy:
        print(f"OpenAPI proxy {mask_proxy_url(proxy)}")
    return VmosApiClient(env["VMOS_ACCESS_KEY"], env["VMOS_SECRET_KEY"], timeout=90, proxy=proxy or None)


def _patch_vps_bot_ports(ssh: VpsSSH, lport: str, rport: str) -> None:
    for k, v in (
        ("BOT_LISTENER_ADB_PORT", rport),
        ("BOT_CLICKER_ADB_PORT", lport),
        ("BOT_ADB_ISOLATED", "1"),
    ):
        ssh.run(
            f"grep -q '^{k}=' {R}/config/bot-start.env && "
            f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || "
            f"echo '{k}={v}' >> {R}/config/bot-start.env",
            12,
        )


def _refresh_side(
    ssh: VpsSSH,
    client: VmosApiClient,
    side: str,
    cfg: dict,
    pads: list,
    models: dict,
) -> bool:
    code = resolve_pad_code(side, cfg, pads, models)
    port = str(cfg["local_port"])
    print(f"\n=== FORCE {side} {code} :{port} ===", flush=True)
    refresh_side_credentials(side, cfg, client, pads, models, max_attempts=5)
    local_tf = ROOT / "config" / f"tunnel-{side}.env"
    check_local = local_tf.read_text(encoding="utf-8") if local_tf.is_file() else ""
    ok = f"LOCAL_PORT={port}" in check_local and "SSH_PASS=" in check_local
    print(local_tf, "written=", ok)
    if ok:
        print(check_local.splitlines()[:6])
    return ok


def _sftp_fallback(ssh: VpsSSH, client: VmosApiClient, side: str, cfg: dict, pads: list, models: dict) -> None:
    code = resolve_pad_code(side, cfg, pads, models)
    port = str(cfg["local_port"])
    bind = str(cfg.get("tunnel_bind") or "")
    try:
        tasks = client.open_adb([code])
        client.wait_open_adb_tasks(tasks, timeout=120)
    except Exception as exc:
        print(f"  open_adb {side}: {exc}")
    adb = fetch_adb_with_backoff(
        client, code, open_adb_first=False, attempts=5,
        wait_for_attempt=lambda i: min(60, 10 * i),
    )
    cmd = rewrite_ssh_forward_port(str(adb.get("command") or ""), port)
    adb_cmd = rewrite_adb_connect_port(str(adb.get("adb") or ""), port)
    host, ssh_port, user = parse_ssh_command(cmd)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
        p = Path(tmp.name)
        write_tunnel_env(
            p, port, host, ssh_port, user, str(adb.get("key") or ""),
            ssh_command=cmd, adb_command=adb_cmd,
            expire_time=str(adb.get("expireTime") or ""),
            expire_minutes="1440", issued_at=_ts(), tunnel_bind_ip=bind,
            header=f"# force {side}",
        )
    try:
        remote = f"{R}/config/tunnel-{side}.env"
        ssh.sftp_put(str(p), remote)
        ssh.run(f"chmod 600 {remote}", 10)
        print(f"  SFTP wrote {remote}")
    finally:
        os.unlink(p)


def main() -> int:
    env = _ensure_local_vmos_api()
    print(f"creds AK={len(env['VMOS_ACCESS_KEY'])} SK={len(env['VMOS_SECRET_KEY'])}")

    client = _client(env)
    pads_cfg = json.loads((ROOT / "config" / "vmos-pads.json").read_text(encoding="utf-8"))
    rport = str((pads_cfg.get("right") or {}).get("local_port") or "58433")
    lport = str((pads_cfg.get("left") or {}).get("local_port") or "55612")
    right_code = str((pads_cfg.get("right") or {}).get("pad_code") or "ATP6416I3I1E6KPM")
    left_code = str((pads_cfg.get("left") or {}).get("pad_code") or "APP5AU4BB269OR35")

    pads: list = []
    models: dict = {}
    try:
        pads = client.list_pads(page=1, rows=50)
        print(f"OpenAPI OK — {len(pads)} pads")
    except Exception as exc:
        print(f"list_pads skip: {exc}")
    pad_codes = [str(p.get("padCode") or "") for p in pads if p.get("padCode")] or [right_code, left_code]

    with VpsSSH(load_vps_config(ROOT)) as ssh:
        ssh.run(
            "pkill -9 -f vps_force_left_tunnel_loop; pkill -9 -f vmos_adb_daemon; "
            f"rm -f {R}/logs/.vmos-refresh.lock; true",
            15,
        )
        print("pushed:", push_runtime_secrets(ssh, ROOT, R))
        _patch_vps_bot_ports(ssh, lport, rport)

        sides = build_daemon_sides(ROOT)
        sides["right"]["local_port"] = rport
        sides["left"]["local_port"] = lport
        ok_r = _refresh_side(ssh, client, "right", sides["right"], pads, models)
        if not ok_r:
            _sftp_fallback(ssh, client, "right", sides["right"], pads, models)
        ok_l = _refresh_side(ssh, client, "left", sides["left"], pads, models)
        if not ok_l:
            _sftp_fallback(ssh, client, "left", sides["left"], pads, models)

        print("re-push tunnel env:", push_runtime_secrets(ssh, ROOT, R))

        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 300))
        for script in ("tunnel-right.sh", "tunnel-left.sh"):
            print(ssh.run(f"bash {R}/scripts/{script} 2>&1 | tail -10", 180))

        out = ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 30)
        print(out)
        online = dual_adb_online(out, rport, lport)
        if online:
            ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -12", 360)
            ssh.run(f"bash {R}/scripts/vmos_adb_daemon_start.sh start 2>&1", 30)
        return 0 if online else 1


if __name__ == "__main__":
    raise SystemExit(main())
