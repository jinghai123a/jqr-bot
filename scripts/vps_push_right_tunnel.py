#!/usr/bin/env python3
"""推送 OpenAPI 右隧道凭证到 VPS（58433）并重连。"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot_ops.config import load_vps_config  # noqa: E402
from bot_ops.ssh_client import VpsSSH  # noqa: E402
from bot_tunnel.env_io import load_env_file, shell_env_line, write_tunnel_env  # noqa: E402
from bot_tunnel.ssh_parse import rewrite_adb_connect_port, rewrite_ssh_forward_port  # noqa: E402

R = "/home/bot/55chat-bot"
VPS_RPORT = "58433"
BIND = "195.114.193.237"


def _refresh_local_right(*, force: bool = False) -> Path:
    p = ROOT / "config" / "tunnel-right.env"
    if p.is_file() and not force:
        env = load_env_file(p)
        if env.get("SSH_PASS") and env.get("VMOS_SSH_COMMAND"):
            print("[use-existing] config/tunnel-right.env", flush=True)
            return p
    import subprocess

    lock = ROOT / "logs" / ".vmos-refresh.lock"
    if lock.is_file():
        try:
            lock.unlink()
        except OSError:
            pass
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "vmos-refresh-tunnels.py"), "--side", "right"],
        cwd=str(ROOT),
        timeout=240,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print(r.stdout[-2000:] if r.stdout else "")
    if r.stderr:
        print(r.stderr[-1000:], file=sys.stderr)
    if r.returncode != 0:
        raise RuntimeError(f"local refresh exit={r.returncode}")
    p = ROOT / "config" / "tunnel-right.env"
    if not p.is_file():
        raise RuntimeError("tunnel-right.env missing after refresh")
    return p


def _normalize_for_vps(src: Path) -> Path:
    env = load_env_file(src)
    ssh_cmd = rewrite_ssh_forward_port(env.get("VMOS_SSH_COMMAND", ""), VPS_RPORT)
    adb_cmd = rewrite_adb_connect_port(env.get("VMOS_ADB_COMMAND", ""), VPS_RPORT)
    if BIND and "-b " not in ssh_cmd and "BindAddress" not in ssh_cmd:
        ssh_cmd = re.sub(r"^ssh\s+", f"ssh -b {BIND} ", ssh_cmd, count=1)
    out = ROOT / "artifacts" / "tunnel-right-vps.env"
    write_tunnel_env(
        out,
        VPS_RPORT,
        env.get("SSH_HOST", ""),
        env.get("SSH_PORT", ""),
        env.get("SSH_USER", ""),
        env.get("SSH_PASS", ""),
        ssh_command=ssh_cmd,
        adb_command=adb_cmd,
        expire_time=env.get("EXPIRE_TIME", ""),
        expire_minutes=env.get("EXPIRE_MINUTES", ""),
        issued_at=env.get("ISSUED_AT", ""),
        tunnel_bind_ip=BIND,
        header="# pushed for APS 58433 — OpenAPI refresh + bind",
    )
    return out


def main() -> int:
    print("=== local OpenAPI refresh (right) ===", flush=True)
    src = _refresh_local_right()
    vps_env = _normalize_for_vps(src)
    cfg = load_vps_config(ROOT)

    with VpsSSH(cfg) as ssh:
        ssh.run(
            "pkill -f 'vmos-refresh-tunnels.py' 2>/dev/null; sleep 1; "
            f"rm -f {R}/logs/.vmos-refresh.lock {R}/data/vmos-refresh.lock; echo locks_cleared",
            20,
        )
        ssh.sftp_put(str(vps_env), f"{R}/config/tunnel-right.env")
        ssh.run(f"chmod 600 {R}/config/tunnel-right.env", 10)
        ssh.run(
            f"pkill -f 'ssh.*{VPS_RPORT}:' 2>/dev/null; "
            f"pkill -f vmos-refresh 2>/dev/null; sleep 2; echo cleared",
            20,
        )
        print("=== tunnel-right on VPS (nohup) ===", flush=True)
        ssh.run(
            f"nohup bash {R}/scripts/tunnel-right.sh > {R}/logs/tunnel-right-push.log 2>&1 </dev/null &",
            15,
        )
        time.sleep(25)
        out = ssh.run(f"tail -20 {R}/logs/tunnel-right-push.log 2>/dev/null; echo ---", 20)
        print(out[-2500:])
        time.sleep(3)
        adb = ssh.run("adb devices -l", 20)
        print(adb)
        ok = VPS_RPORT in adb and "device" in adb.split(VPS_RPORT)[1][:20]
        if ok:
            print(ssh.run(f"adb -s 127.0.0.1:{VPS_RPORT} shell getprop ro.product.model", 20))
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
