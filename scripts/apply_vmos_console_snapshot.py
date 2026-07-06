#!/usr/bin/env python3
"""从 config/vmos-console-snapshot.json 写入 tunnel-*.env 并推送 VPS 重连。"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_JSON = ROOT / "config" / "vmos-console-snapshot.json"
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config
from bot_ops.deploy_secrets import push_runtime_secrets
from bot_ops.ssh_client import VpsSSH
from bot_ops.vps_ports import dual_adb_online, dual_adb_ports
from bot_tunnel.env_io import write_tunnel_env

R = "/home/bot/55chat-bot"
BJ = ZoneInfo("Asia/Shanghai")


def _load_snapshot() -> dict:
    return json.loads(SNAPSHOT_JSON.read_text(encoding="utf-8"))


def _issued_expire() -> tuple[str, str]:
    now = datetime.now(BJ)
    exp = now + timedelta(hours=24)
    return now.strftime("%Y-%m-%d %H:%M:%S"), exp.strftime("%Y-%m-%d %H:%M:%S")


def _write_side(side: str, cfg: dict) -> Path:
    pwd = cfg["ssh_pass"]
    if len(pwd) < 200:
        raise SystemExit(
            f"[{side}] ssh_pass 仅 {len(pwd)} 字符，疑似截断；"
            "请从 VMOS 控制台「复制」完整密钥（约 236 字符）后保存 snapshot 再执行"
        )
    port = str(cfg["prod_local_port"])
    host = cfg["console_ssh_host"]
    sport = str(cfg["console_ssh_port"])
    user = cfg["console_ssh_user"]
    bind = cfg["tunnel_bind"]
    ssh_cmd = (
        f"ssh -oStrictHostKeyChecking=accept-new {user}@{host} -p {sport} "
        f"-L {port}:localhost:1 -Nf"
    )
    adb_cmd = f"adb -P {cfg['adb_server_port']} connect localhost:{port}"
    issued, expire = _issued_expire()
    path = ROOT / "config" / f"tunnel-{side}.env"
    write_tunnel_env(
        path,
        port,
        host,
        sport,
        user,
        pwd,
        ssh_command=ssh_cmd,
        adb_command=adb_cmd,
        expire_time=expire,
        expire_minutes="1440",
        issued_at=issued,
        tunnel_bind_ip=bind,
        header=(
            f"# {cfg['pad_code']} {cfg['role']} — console L {cfg['console_local_port']} "
            f"-> prod {port} ({cfg.get('_updated', '')})"
        ),
    )
    return path


def _sync_pads_meta(snap: dict) -> None:
    pads_path = ROOT / "config" / "vmos-pads.json"
    pads = json.loads(pads_path.read_text(encoding="utf-8"))
    pads["_console_snapshot"] = snap.get("_updated", "")
    for side in ("left", "right"):
        s = snap[side]
        pads[side].update(
            {
                "pad_code": s["pad_code"],
                "match_android": s["android"],
                "match_egress_ip": s["tunnel_bind"],
                "local_port": s["prod_local_port"],
                "adb_server_port": s["adb_server_port"],
                "console_export_ip": s.get("export_ip"),
                "console_ssh_host": s.get("console_ssh_host"),
                "console_adb_port": s.get("console_local_port"),
            }
        )
    pads_path.write_text(json.dumps(pads, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    snap = _load_snapshot()
    _sync_pads_meta(snap)
    for side in ("left", "right"):
        p = _write_side(side, snap[side])
        c = snap[side]
        print(f"wrote {p.name} {c['pad_code']} :{c['prod_local_port']} gw={c['console_ssh_host']}")

    rport, lport = dual_adb_ports(ROOT)
    with VpsSSH(load_vps_config(ROOT)) as ssh:
        for k, v in (
            ("BOT_LISTENER_ADB_PORT", rport),
            ("BOT_CLICKER_ADB_PORT", lport),
            ("BOT_ADB_ISOLATED", "1"),
        ):
            ssh.run(
                f"grep -q '^{k}=' {R}/config/bot-start.env && "
                f"sed -i 's/^{k}=.*/{k}={v}/' {R}/config/bot-start.env || echo '{k}={v}' >> {R}/config/bot-start.env",
                12,
            )
        print("pushed", push_runtime_secrets(ssh, ROOT, R))
        ssh.sftp_put(str(ROOT / "config" / "vmos-pads.json"), f"{R}/config/vmos-pads.json")
        ssh.sftp_put(str(SNAPSHOT_JSON), f"{R}/config/vmos-console-snapshot.json")
        print(ssh.run(f"bash {R}/scripts/reconnect-dual-adb.sh 2>&1", 300))
        for sh in ("tunnel-right.sh", "tunnel-left.sh"):
            print(ssh.run(f"bash {R}/scripts/{sh} 2>&1 | tail -12", 180))
        out = ssh.run("adb -P 5038 devices -l; echo ---; adb -P 5039 devices -l", 30)
        print(out)
        ok = dual_adb_online(out, rport, lport)
        if ok:
            print(ssh.run(f"bash {R}/scripts/reload-dual-workers.sh 2>&1 | tail -12", 360))
        ssh.run(f"bash {R}/scripts/vmos_adb_daemon_start.sh start 2>&1", 25)
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
