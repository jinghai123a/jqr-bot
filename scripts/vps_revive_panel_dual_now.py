#!/usr/bin/env python3
"""重启 Panel :3000（新 IP 回调）+ 双机隧道 + 群聊发图/公告验收。"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402
from bot_ops.vps_ports import dual_adb_online, dual_adb_ports  # noqa: E402
from bot_tunnel import (  # noqa: E402
    fetch_adb_with_backoff,
    parse_ssh_command,
    rewrite_adb_connect_port,
    rewrite_ssh_forward_port,
    write_tunnel_env,
)
from scripts.vmos_api.transport import mask_proxy_url, proxy_from_env  # noqa: E402
from scripts.vmos_api_client import VmosApiClient  # noqa: E402

R = "/home/bot/55chat-bot"
PY = f"{R}/.venv/bin/python3"
CALLBACK_IP = "195.114.193.136"
CALLBACK = f"http://{CALLBACK_IP}:3000/api/vmos/callback"
PADS_JSON = ROOT / "config" / "vmos-pads.json"


def _ts() -> str:
    return datetime.now(tz=ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _parse_env_raw(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.strip().split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _vmos_client(ssh: VpsSSH) -> VmosApiClient:
    env = _parse_env_raw(ssh.run(f"cat {R}/config/vmos-api.env", 20))
    proxy = proxy_from_env(env)
    if proxy:
        print(f"  OpenAPI proxy {mask_proxy_url(proxy)}", flush=True)
    ak = env.get("VMOS_ACCESS_KEY") or env.get("VMOS_AK") or ""
    sk = env.get("VMOS_SECRET_KEY") or env.get("VMOS_SK") or ""
    if not ak or not sk:
        raise RuntimeError("missing VMOS creds on VPS")
    return VmosApiClient(ak, sk, timeout=120, proxy=proxy or None)


def _push_tunnel_env(
    ssh: VpsSSH,
    side: str,
    *,
    port: str,
    host: str,
    ssh_port: str,
    user: str,
    password: str,
    ssh_command: str,
    adb_command: str,
    expire_time: str,
    bind_ip: str,
) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
        p = Path(tmp.name)
        write_tunnel_env(
            p,
            port,
            host,
            ssh_port,
            user,
            password,
            ssh_command=ssh_command,
            adb_command=adb_command,
            expire_time=expire_time,
            expire_minutes="1440",
            issued_at=_ts(),
            tunnel_bind_ip=bind_ip,
            header=f"# revive {side}",
        )
    try:
        remote = f"{R}/config/tunnel-{side}.env"
        ssh.sftp_put(str(p), remote)
        ssh.run(f"chmod 600 {remote}", 10)
    finally:
        os.unlink(p)


def _refresh_side_credentials(ssh: VpsSSH, client: VmosApiClient, side: str, cfg: dict) -> bool:
    code = str(cfg.get("pad_code") or "")
    port = str(cfg.get("local_port") or "")
    bind = str(cfg.get("match_egress_ip") or "")
    print(f"\n[{_ts()}] refresh {side} {code} :{port} bind={bind}", flush=True)
    try:
        tasks = client.open_adb([code])
        client.wait_open_adb_tasks(tasks, timeout=180)
    except Exception as exc:
        print(f"  open_adb warn: {exc}", flush=True)
    try:
        adb = fetch_adb_with_backoff(
            client,
            code,
            open_adb_first=False,
            attempts=8,
            wait_for_attempt=lambda i: min(90, 10 * i),
        )
    except Exception as exc:
        print(f"  get_adb FAIL: {exc}", flush=True)
        return False
    cmd = rewrite_ssh_forward_port(str(adb.get("command") or ""), port)
    adb_cmd = rewrite_adb_connect_port(str(adb.get("adb") or ""), port)
    key = str(adb.get("key") or "")
    host, ssh_port, user = parse_ssh_command(cmd)
    if not host or not key:
        print("  bad adb command/key", flush=True)
        return False
    _push_tunnel_env(
        ssh,
        side,
        port=port,
        host=host,
        ssh_port=ssh_port,
        user=user,
        password=key,
        ssh_command=cmd,
        adb_command=adb_cmd,
        expire_time=str(adb.get("expireTime") or ""),
        bind_ip=bind,
    )
    print(f"  cred ok {host}:{ssh_port}", flush=True)
    return True


def _restart_panel(ssh: VpsSSH) -> bool:
    print(f"\n[{_ts()}] === restart panel on {CALLBACK_IP}:3000 ===", flush=True)
    env_path = f"{R}/.env"
    env_raw = ssh.run(f"test -f {env_path} && cat {env_path} || echo ''", 15)
    new_line = f'APP_URL="http://{CALLBACK_IP}:3000"'
    if re.search(r"^APP_URL=", env_raw, re.M):
        env_raw = re.sub(r"^APP_URL=.*", new_line, env_raw, flags=re.M)
    else:
        env_raw = (env_raw.rstrip() + "\n" + new_line + "\n").lstrip()
    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".env") as tmp:
        p = Path(tmp.name)
        p.write_text(env_raw, encoding="utf-8")
    try:
        ssh.sftp_put(str(p), env_path)
        ssh.run(f"chmod 600 {env_path}", 10)
    finally:
        os.unlink(p)
    print(ssh.run(f"grep '^APP_URL=' {env_path}", 10))

    ssh.run("pkill -f 'node dist/server' 2>/dev/null; sleep 2; true", 20)
    ssh.run(f"cd {R} && nohup node dist/server.cjs >> logs/server.log 2>&1 &", 10)
    time.sleep(5)
    proc = ssh.run("pgrep -af 'node dist/server' | head -2", 15)
    listen = ssh.run("ss -tlnp 2>/dev/null | grep ':3000' | head -3", 15)
    print(proc)
    print(listen)
    code = ssh.run(
        f"curl -s -o /dev/null -w '%{{http_code}}' -X POST {CALLBACK} "
        f"-H 'Content-Type: application/json' "
        f"-d '{{\"taskBusinessType\":999,\"padCode\":\"revive-test\",\"taskStatus\":3}}'",
        20,
    ).strip()
    tail = ssh.run(f"tail -1 {R}/logs/vmos-callback.log 2>/dev/null || echo no_log", 10)
    print(f"callback_http={code}")
    print(f"callback_log={tail.strip()}")
    return code in ("200", "201") and "node dist/server" in proc


def _bring_up_tunnels(ssh: VpsSSH, rport: str, lport: str) -> bool:
    print(f"\n[{_ts()}] === OpenAPI refresh + tunnels ===", flush=True)
    ssh.run(
        "pkill -9 -f vmos-refresh-tunnels.py 2>/dev/null || true; "
        f"rm -f {R}/data/vmos-refresh.lock {R}/logs/.vmos-refresh.lock; true",
        15,
    )
    pads = json.loads(PADS_JSON.read_text(encoding="utf-8"))
    client = _vmos_client(ssh)
    ok_r = _refresh_side_credentials(ssh, client, "right", pads.get("right") or {})
    ok_l = _refresh_side_credentials(ssh, client, "left", pads.get("left") or {})

    print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 180))
    if not ok_r:
        print(ssh.run(f"bash {R}/scripts/tunnel-right.sh 2>&1 | tail -12", 120))
    if not ok_l:
        print(ssh.run(f"bash {R}/scripts/tunnel-left.sh 2>&1 | tail -12", 120))

    out = ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 25)
    print(out)
    return dual_adb_online(out, rport, lport)


def _restart_dual_stack(ssh: VpsSSH) -> str:
    print(f"\n[{_ts()}] === restart dual stack (both sides) ===", flush=True)
    for kv in (
        "BOT_LISTENER_OPTIONAL=0",
        "BOT_DUAL_PROCESS=1",
        "BOT_CLICKER_SEND_ANNOUNCE=1",
        "BOT_CLICKER_SEND_IMAGES=1",
    ):
        k, v = kv.split("=", 1)
        ssh.run(
            f"grep -q '^{k}=' {R}/config/bot-start.env && "
            f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || "
            f"echo '{k}={v}' >> {R}/config/bot-start.env",
            12,
        )
    ssh.run("pkill -15 -f bot_dual_supervisor 2>/dev/null; pkill -15 -f spawn_main 2>/dev/null; sleep 3; true", 20)
    ssh.run(f"bash {R}/scripts/edge_brain_start.sh 2>&1 | tail -3", 20)
    reload = ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -25", 360)
    if "spawn_main" not in ssh.run("pgrep -af spawn_main | grep -v pgrep", 15):
        reload += "\n--- fallback restart-55chat-bot ---\n"
        reload += ssh.run(f"bash {R}/scripts/restart-55chat-bot.sh 2>&1 | tail -15", 120)
    time.sleep(10)
    return reload


def _smoke_tests(ssh: VpsSSH, rport: str, lport: str) -> tuple[bool, bool]:
    print(f"\n[{_ts()}] === smoke: announce + verify ===", flush=True)
    announce = ssh.run(
        f"set -a; . {R}/config/bot-start.env; set +a; cd {R} && {PY} scripts/vps_force_left_out_now.py 2>&1",
        150,
    )
    print(announce[-2000:])
    ann_ok = "OK:" in announce or "announce visible" in announce

    verify = ssh.run(
        f"cd {R} && {PY} scripts/verify_group_announce_outgoing.py "
        f"--left localhost:{lport} --right localhost:{rport} 2>&1",
        180,
    )
    print(verify[-1500:])
    verify_ok = "verdict=PASS" in verify

    visual = ssh.run(
        f"W49_VISUAL_CAPTURE_DIR={R}/logs/visual-captures "
        f"{PY} {R}/scripts/vmos_visual_monitor.py --both --once 2>&1 | grep state=",
        120,
    )
    print(visual)
    img_ok = visual.count("state=target_group") >= 1
    return ann_ok or verify_ok, img_ok or verify_ok


def main() -> int:
    rport, lport = dual_adb_ports(ROOT)
    rc = 0
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        if not _restart_panel(ssh):
            print("WARN: panel/callback not fully verified", flush=True)
            rc = 1

        tunnels_ok = _bring_up_tunnels(ssh, rport, lport)
        if not tunnels_ok:
            print("WARN: ADB tunnels not both online", flush=True)
            rc = 1

        print(_restart_dual_stack(ssh)[-2500:])

        if tunnels_ok:
            ann_ok, img_ok = _smoke_tests(ssh, rport, lport)
            if not ann_ok:
                print("FAIL: announce smoke", flush=True)
                rc = 1
            if not img_ok:
                print("WARN: visual target_group incomplete", flush=True)
        else:
            rc = 1

        print(
            ssh.run(
                f"pgrep -af 'node dist/server|bot_dual_supervisor|spawn_main|edge_brain' | grep -v pgrep; "
                f"echo '---'; adb -P 5038 devices; echo '---'; adb -P 5039 devices",
                25,
            )
        )
    print(f"REVIVE_RC={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
